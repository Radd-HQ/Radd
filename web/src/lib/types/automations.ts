/** Automation rules (specs 20/58/66/69). */
import type { CustomFieldValue } from "./items";
// ---------------------------------------------------------------------------
// Automations (spec 20 — /automations). Global rules that react to an
// item event, match an SLQ condition, and apply an ordered list of actions.
// ---------------------------------------------------------------------------

/** A rule's trigger is an event-type string from GET /automations/catalog
 * ("item.updated", "comment.created", …) — or a sentinel. `manual` rules
 * never fire from events: they run on demand from the editor's `/` quick-action
 * menu (POST /automations/{id}/run). */
export const MANUAL_TRIGGER = "manual";

/** Spec 69: the schedule sentinel — the rule fires from the scheduler clock
 * instead of an event, driven by its `schedule` config. */
export const SCHEDULE_TRIGGER = "schedule";

/** Shape of a scheduled rule's `schedule` (spec 69, mirror of ScheduleKind). */
export const ScheduleKind = {
  interval: "interval",
  daily: "daily",
  weekly: "weekly",
  monthly: "monthly",
  cron: "cron",
} as const;
export type ScheduleKindValue = (typeof ScheduleKind)[keyof typeof ScheduleKind];

/** interval: {minutes >= 5}; daily: {time "HH:MM"}; weekly: {time, weekdays
 * (0=Mon, non-empty)}; monthly: {time, day}; cron: {expression}. Times run on
 * the server's scheduler timezone. */
export interface RuleSchedule {
  kind: ScheduleKindValue;
  minutes?: number | null;
  time?: string | null;
  weekdays?: number[] | null;
  /** Monthly: day of the month, clamped to the month's last day. */
  day?: number | null;
  /** Cron: a five-field expression, validated server-side. */
  expression?: string | null;
}

/** One subscribable event type, from GET /automations/catalog (spec 58). */
export interface TriggerInfo {
  event_type: string;
  label: string;
  group: string;
  /** A target item resolves — the SLQ condition + item actions apply to it. */
  item_scoped: boolean;
  /** The payload carries a field diff (changed-field/old/new subjects work). */
  has_changes: boolean;
}

export const ConditionSubject = {
  actor: "actor",
  changedField: "changed_field",
  oldValue: "old_value",
  newValue: "new_value",
  stateCategory: "state_category",
  payload: "payload",
} as const;
export type ConditionSubjectValue = (typeof ConditionSubject)[keyof typeof ConditionSubject];

export const ConditionGroupOp = { all: "all", any: "any", none: "none" } as const;
export type ConditionGroupOpValue =
  (typeof ConditionGroupOp)[keyof typeof ConditionGroupOp];

/** One leaf condition on the triggering event (spec 58). */
export interface EventCondition {
  subject: ConditionSubjectValue;
  /** Field name (old/new value) or dotted payload path — where the subject needs one. */
  qualifier?: string | null;
  operator: string;
  value?: string | number | boolean | string[] | null;
}

/** A nestable all/any/none group of conditions. */
export interface ConditionGroup {
  op: ConditionGroupOpValue;
  conditions: (ConditionGroup | EventCondition)[];
}

export interface SubjectInfo {
  key: ConditionSubjectValue;
  label: string;
  needs_qualifier: boolean;
  qualifier_hint: string;
  requires_changes: boolean;
}

export interface OperatorInfo {
  key: string;
  label: string;
  needs_value: boolean;
  list_value: boolean;
}

/** A node type contributed through the kernel registry (spec 116 phase 2).
 * Served rather than hardcoded: which nodes exist depends on which plugins are
 * installed, so a baked-in palette would offer the AI classifier on an instance
 * without the AI module. */
export interface ContributedNodeInfo {
  key: string;
  kind: NodeKindValue;
  label: string;
  description: string;
  group: string;
  params_schema: Record<string, unknown>;
  default_ports: string[];
  needs_items: boolean;
  permission: string;
}

/** GET /automations/catalog — everything the rule builder renders from. */
export interface AutomationCatalog {
  triggers: TriggerInfo[];
  subjects: SubjectInfo[];
  operators: OperatorInfo[];
  manual_trigger: string;
  /** Spec 69: the "On a schedule" sentinel + the schedule kinds it offers. */
  schedule_trigger: string;
  schedule_kinds: { key: ScheduleKindValue; label: string }[];
  contributed_nodes: ContributedNodeInfo[];
  /** How each node type reads its packet, built-in and contributed alike. */
  node_arity: NodeArityInfo[];
  /** `{{token}}` substitutions available in action text fields. Served so the
   * editor can SHOW what is supported instead of leaving people guessing. */
  tokens: { token: string; description: string; needs_item: boolean }[];
  /** Whether the CALLER may make an action run as someone else. The Act as
   * field is not rendered at all when false. */
  can_act_as: boolean;
}

/** What a matching rule does to an item (mirror of backend `ActionType`). */
export const ActionType = {
  setState: "set_state",
  setPriority: "set_priority",
  setAssignee: "set_assignee",
  setTeam: "set_team",
  addLabel: "add_label",
  removeLabel: "remove_label",
  setCycle: "set_cycle",
  setRelease: "set_release",
  setCustomField: "set_custom_field",
  addComment: "add_comment",
  // Universal actions (spec 58b) — run with or without a target item; their
  // text params accept {{event_type}}/{{actor.*}}/{{payload.*}}/{{item.*}}.
  createItem: "create_item",
  sendWebhook: "send_webhook",
  postChat: "post_chat",
  notifyUser: "notify_user",
  sendEmail: "send_email",
} as const;
export type ActionTypeValue = (typeof ActionType)[keyof typeof ActionType];

/**
 * Role values the send_email action's `to` param may name (spec 66) — anything
 * else is a literal address. Roles resolve against the event's target item.
 */
export const EmailRecipient = {
  reporter: "reporter",
  assignee: "assignee",
  contact: "contact",
} as const;

/**
 * One rule action as sent to the API — `{type, params}` where params is
 * type-specific (state name / priority / assignee email / team|cycle name /
 * label / release version / {key,value} / {body,visibility}). Names resolve per
 * item at apply time; `"none"` clears assignee/team/cycle/release.
 */
export interface RuleAction {
  type: ActionTypeValue;
  params: Record<string, CustomFieldValue>;
}

/** GET /automations — actions arrive opaque (`{type, params}`). */
/** Member-visible slice of an enabled manual rule — the `/` menu's custom actions. */
export interface RunnableRule {
  id: string;
  name: string;
}

// ---------------------------------------------------------------------------
// The graph (spec 116). An automation is a DAG: a TRIGGER emits a packet of
// (event facts, item set); FILTER narrows the set across matched/unmatched;
// GATE routes the whole packet by a boolean over the event; ACTION does work and
// passes its input through so chains continue.
//
// `trigger` and `schedule` are NOT sent — the server derives them from the
// trigger node, so there is one place that says what starts an automation.
// ---------------------------------------------------------------------------

export const NodeKind = {
  trigger: "trigger",
  /** Produces items rather than narrowing them — the SLQ search node. Every
   * other kind can only reduce what the trigger handed it, so without this an
   * automation could never reach an issue the event did not name. */
  source: "source",
  filter: "filter",
  gate: "gate",
  action: "action",
} as const;
export type NodeKindValue = (typeof NodeKind)[keyof typeof NodeKind];

/** The built-in port names. A node TYPE may name its own — an AI classifier's
 * ports are its answers — so an edge's port is a plain string, checked against
 * the source node's real ports on write. */
export const NodePort = {
  out: "out",
  matched: "matched",
  unmatched: "unmatched",
  true: "true",
  false: "false",
  /** What `create_item` MADE, as opposed to what it was given. */
  created: "created",
} as const;
export type NodePortValue = (typeof NodePort)[keyof typeof NodePort];

/** How a node reads its input packet (RADD-918).
 *
 * There is no loop node: in a dataflow graph over sets, "for each" is not
 * control flow but how a node reads its input. `set` runs once over the whole
 * packet; `item` runs per item — which for a ROUTER means partitioning the set
 * across its ports rather than sending all of it down one. */
export const NodeArity = { set: "set", item: "item" } as const;
export type NodeArityValue = (typeof NodeArity)[keyof typeof NodeArity];

/** How one node type may read its packet. `options` of length one means fixed,
 * and the editor shows no control — a toggle with one setting teaches nothing.
 * Served rather than mirrored here: a default that disagrees with the server is
 * invisible, because nothing fails to compile. */
export interface NodeArityInfo {
  type: string;
  default: NodeArityValue;
  options: NodeArityValue[];
}

/** What a search node does with the packet it was handed. */
export const SearchMode = { replace: "replace", add: "add" } as const;

export interface AutomationNode {
  id: string;
  kind: NodeKindValue;
  /** The node-type key: "trigger.event", "filter.slq", "action.add_label", … */
  type: string;
  params: Record<string, unknown>;
  /** Canvas coordinates. Optional and ignored by the engine — absent means
   * "nobody has placed this node", and the editor lays it out from the topology
   * instead. That is what lets every automation migrated by d116graphs open on
   * the canvas without a data migration inventing positions. */
  x?: number | null;
  y?: number | null;
}

export interface AutomationEdge {
  source: string;
  /** A plain string, not `NodePortValue`: a contributed node's ports are its
   * own — an AI classifier's are the answers someone typed. The server checks
   * the name against the SOURCE node's real ports. */
  port: string;
  target: string;
}

/** One TRIGGER node, projected by the server with its scheduler stamps.
 * A list, not a scalar: a graph may hold several triggers, and one
 * `next_run_at` could only ever describe one of them. */
export interface RuleTrigger {
  node_id: string;
  event_type: string;
  schedule: RuleSchedule | null;
  next_run_at: string | null;
  last_run_at: string | null;
}

export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  nodes: AutomationNode[];
  edges: AutomationEdge[];
  position: number;
  /** Which way the canvas flows. Stored per automation, not per viewer. */
  orientation: "vertical" | "horizontal";
  triggers: RuleTrigger[];
  created_at: string;
  updated_at: string;
}

export interface RuleCreate {
  name: string;
  enabled?: boolean;
  position?: number;
  orientation?: "vertical" | "horizontal";
  nodes: AutomationNode[];
  edges: AutomationEdge[];
}

/** PATCH /automations/{id} — omitted keys untouched. The graph is replaced whole
 * or not at all: sending nodes without edges keeps the stored edges, and the
 * pair is re-validated together. */
export interface RuleUpdate {
  name?: string;
  enabled?: boolean;
  position?: number;
  orientation?: "vertical" | "horizontal";
  nodes?: AutomationNode[];
  edges?: AutomationEdge[];
}

/** One action's dry-run outcome (POST /automations/{id}/test). */
export interface ActionPreview {
  type: ActionTypeValue;
  params: Record<string, unknown>;
  /** False when a named target no longer resolves (the engine would skip it). */
  resolves: boolean;
  detail: string;
  /** Which node planned it, against which item — a graph runs the same action
   * type from several nodes, and once per item at per-item arity. */
  node_id: string;
  item_key: string;
}

/** What left one port of one node on a dry run. */
export interface PortResult {
  port: string;
  /** Exact, even when `sample` is capped. */
  count: number;
  /** Item keys — a sample you can recognise, which a count cannot be. */
  sample: string[];
  /** False = the node did not emit this port AT ALL (a gate's untaken branch).
   * Different from emitting zero items, which is a filter matching nothing. */
  taken: boolean;
}

/** One node's dry run. */
export interface NodeResult {
  node_id: string;
  kind: NodeKindValue;
  type: string;
  /** False = never reached: detached from the trigger, or out of budget. */
  ran: boolean;
  incoming: number;
  incoming_sample: string[];
  ports: PortResult[];
}

/** POST /automations/{id}/test — what the graph would do, per node. */
export interface RuleTestResult {
  rule_id: string;
  /** Null when the run had no seed item (a schedule- or search-fed graph). */
  item_id: string | null;
  matched: boolean;
  would_apply: ActionPreview[];
  trigger_node_id: string;
  nodes: NodeResult[];
  /** Budget truncation, surfaced rather than buried in a log. */
  dropped: string[];
}

/** One addressable path into an event payload, with values really seen at it.
 * The string is what `{{payload.<path>}}` and the payload condition take. */
export interface PayloadPathInfo {
  path: string;
  examples: string[];
  /** Inside a list — a template reading it may render several values, joined. */
  repeated: boolean;
}

/** GET /automations/samples/events — what an event type actually carries.
 * Sampled from REAL events; `sampled: 0` means this type has never fired here,
 * which the UI says rather than inventing a shape. */
export interface EventSample {
  event_type: string;
  sampled: number;
  paths: PayloadPathInfo[];
  /** Field names seen in `changes` diffs — what "field changed" can test. */
  changed_fields: string[];
  example: Record<string, unknown> | null;
  /** Entity types this event is ABOUT (RADD-923). Each appears in the payload as
   * a canonical ref under its own key, written by the kernel — so these resolve
   * whether or not the event has ever fired here. */
  subjects: string[];
  /** The event's own DECLARED shape, beyond the refs. Present even when
   * `sampled` is 0 — sampling says what has happened, declaration what will. */
  declared_schema: Record<string, unknown>;
}
