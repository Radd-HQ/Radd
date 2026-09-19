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

/** Spec 119: the validation sentinel. The graph runs SYNCHRONOUSLY at intake,
 * against a savepoint-created draft, and applies nothing — it produces findings.
 * Like the other two it is not in the event catalog, so nothing can fire it from
 * the event stream. */
export const VALIDATE_TRIGGER = "validate";

/** What a validate trigger governs. A LIST of these rides on the node — one
 * graph may check a form, an issue type and a project at once. */
export const ValidationTargetKind = {
  form: "form",
  issueType: "issue_type",
  project: "project",
} as const;
export type ValidationTargetKindValue =
  (typeof ValidationTargetKind)[keyof typeof ValidationTargetKind];

export interface ValidationTarget {
  kind: ValidationTargetKindValue;
  id: string;
}

/** How hard a governing graph's findings bite. `advisory` shows them and allows
 * "create anyway"; `required` refuses, for every caller including the API. */
export const ValidationMode = { advisory: "advisory", required: "required" } as const;
export type ValidationModeValue = (typeof ValidationMode)[keyof typeof ValidationMode];

/** The node type that RECORDS a finding and passes its packet through, so
 * several checks can chain off one branch. An ACTION kind on the server (its
 * ports are an action's `out`), which is why it appears under Actions. */
export const VALIDATION_FAIL_TYPE = "validation.fail";

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

/** POST /automations/schedule/preview — when a candidate schedule would run.
 * Computed on the server so the answer is the engine's own arithmetic, and
 * `error` carries the refusal the save would give (RADD-912). */
export interface SchedulePreview {
  timezone: string;
  next_runs: string[];
  error: string | null;
}

/** One subscribable event type, from GET /automations/catalog (spec 58). */
export interface TriggerInfo {
  event_type: string;
  label: string;
  group: string;
  /** A target item resolves — the SLQ condition + item actions apply to it. */
  item_scoped: boolean;
  /** The payload carries a field diff (the field-changed gate can read it). */
  has_changes: boolean;
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
  /** The node's FIXED ports (RADD-1064). Empty means its outputs depend on its
   * params — an AI classifier's ports are the answers being typed — and the
   * editor computes those locally instead. Without this the canvas could only
   * fall back to the KIND's table, which drew `ai.validate` (a gate) with
   * TRUE/FALSE handles and let people wire edges the engine never emits. */
  ports: string[];
  default_ports: string[];
  /** The node's FIXED named outputs (spec 120), on exactly the terms `ports` is
   * fixed: empty means they depend on the params — `ai.generate`'s outputs ARE
   * the fields someone is still typing — and the editor computes those locally
   * as the form changes. */
  outputs: OutputFieldInfo[];
  needs_items: boolean;
  permission: string;
}

/** One value a node produces, addressable downstream as `{{<node>.<name>}}`. */
export interface OutputFieldInfo {
  name: string;
  label: string;
  /** "text" | "enum" — an enum's `choices` are what the model may answer. */
  kind: string;
  choices: string[];
  description: string;
}

/** What one BUILT-IN node type produces. Served beside `node_arity` and for the
 * same reason: a second copy of `action.create_item -> key, id, url` in
 * TypeScript is a copy that drifts. */
export interface NodeOutputsInfo {
  type: string;
  outputs: OutputFieldInfo[];
}

/** GET /automations/catalog — everything the rule builder renders from. */
export interface AutomationCatalog {
  triggers: TriggerInfo[];
  operators: OperatorInfo[];
  manual_trigger: string;
  /** Spec 69: the "On a schedule" sentinel + the schedule kinds it offers. */
  schedule_trigger: string;
  schedule_kinds: { key: ScheduleKindValue; label: string }[];
  contributed_nodes: ContributedNodeInfo[];
  /** How each node type reads its packet, built-in and contributed alike. */
  node_arity: NodeArityInfo[];
  /** What each BUILT-IN node type produces (spec 120). Contributed types carry
   * theirs on `contributed_nodes[].outputs`. */
  node_outputs: NodeOutputsInfo[];
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
  // Round-robin distribution across a team (RADD-1044). Always per-item — "the
  // next member" is a property of one issue — so the server fixes its arity.
  assignRoundRobin: "assign_round_robin",
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
  /** What downstream tokens call this node (spec 120) — the left half of
   * `{{triage.priority}}`. Separate from `id`, which edges are wired to: naming
   * would otherwise be a graph-wide rewire. Absent/empty = unaddressable, which
   * is right for the node types that produce nothing. */
  name?: string;
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
  /** `{{token}}` -> what it rendered to. Only params that CARRIED a token
   * appear; when `resolves` is false, this is what `detail` is about. */
  resolved: Record<string, string>;
}

/** One value a node produced on a dry run, with the token that reads it. The
 * token rather than the bare field name, because that is the thing someone
 * copies into the action below. */
export interface ProducedVar {
  token: string;
  name: string;
  value: string;
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
  /** What downstream tokens call this node, "" when unnamed. */
  name: string;
  /** What it produced. Present even when unnamed — that is the mistake it
   * exists to show. */
  produced: ProducedVar[];
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
  /** What a VALIDATION graph would tell the submitter (spec 119). Empty for
   * every other kind of graph — which is the honest answer, not a missing one. */
  findings: Finding[];
}

// ---------------------------------------------------------------------------
// Intake validation (spec 119) — the surfaces a submitter sees.
// ---------------------------------------------------------------------------

/** One thing wrong with a draft. `field` is a builtin name (`title`,
 * `description`, `assignee`, …) or `cf.<key>`, and empty when the finding is
 * about the submission as a whole — the two render differently: one against the
 * control it names, one in the panel. */
export interface Finding {
  message: string;
  field: string;
  /** Which check said it. Not shown; it is what makes a message traceable back
   * to the node that produced it. */
  node_id: string;
}

export interface IntakeVerdict {
  /** Whether anything governs this draft at all — NOT the same as `passed`,
   * which an ungoverned draft also satisfies. */
  governed: boolean;
  /** The STRICTEST mode among the graphs governing this draft — what kind of
   * thing is watching, for display. NOT what happened: see `blocking`. */
  mode: ValidationModeValue;
  passed: boolean;
  /** Whether these findings REFUSE the creation. The server's `verdict.blocks`,
   * and the same property `commit: "always"` is answered 409 by — so a client
   * gates "create anyway" on this and never on `mode === "required"`, which is
   * a different question and answers it wrongly whenever a required graph and
   * an advisory one govern the same draft and only the advisory one trips. */
  blocking: boolean;
  findings: Finding[];
}

/** What to do with the draft once the checks have spoken. */
export const IntakeCommit = {
  /** Create it when it passes, take it back when it does not. The default. */
  pass: "pass",
  /** Create it regardless — the advisory "create anyway". 409 where required. */
  always: "always",
  /** Create nothing; a pure pre-flight. */
  never: "never",
} as const;
export type IntakeCommitValue = (typeof IntakeCommit)[keyof typeof IntakeCommit];

/** GET /items/validate/context — whether the button should say Validate, and
 * whether "create anyway" is on offer. `mode` is null exactly when nothing
 * governs, so "advisory" cannot be mistaken for "ungoverned". */
export interface ValidationContext {
  governed: boolean;
  mode: ValidationModeValue | null;
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
