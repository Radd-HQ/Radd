/** Automation wire types — mirrors `automations/schemas.py`. */
/** A param value in the `{type, params}` shape `ActionParams` edits. */
export type ActionParamValue = string | number | boolean | string[] | null;

/** Trigger sentinels — not event types, so nothing on the event stream fires them: `manual` runs on
 * demand (POST /automations/{id}/run), `schedule` from the clock, `validate` synchronously at intake
 * against a draft, applying nothing. */
export const MANUAL_TRIGGER = "manual";
export const SCHEDULE_TRIGGER = "schedule";
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

/** The validation VERDICT nodes (RADD-1329): terminal, the only things that
 * speak to the person submitting. Block refuses; Warn advises. */
export const VERDICT_BLOCK_TYPE = "verdict.block";
export const VERDICT_WARN_TYPE = "verdict.warn";

import type { ScheduleConfig as RuleSchedule, ScheduleKindValue } from "@radd/plugin-sdk";
export type { RuleSchedule };

/** One subscribable event type, from GET /automations/catalog (spec 58). */
export interface TriggerInfo {
  plugin: string;
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

/** A node type from the kernel registry — built-in and contributed alike, served because which
 * nodes exist depends on the loaded plugins. */
interface NodeInfo {
  key: string;
  /** Registry owner, used to reject retained catalogs after withdrawal. */
  plugin: string;
  kind: NodeKindValue;
  label: string;
  description: string;
  group: string;
  params_schema: Record<string, unknown>;
  /** Extra words the palette search matches. */
  keywords: string;
  /** The params a fresh node starts with. Empty = the schema's own defaults. */
  default_params: Record<string, unknown>;
  /** Reads the triggering event — refused under a trigger that has none. */
  reads_event: boolean;
  /** Publishes findings a verdict node can relay (RADD-1329). */
  produces_findings: boolean;
  /** RADD-1325: ports / outputs depend on params — the shape endpoint answers. */
  dynamic_ports: boolean;
  dynamic_outputs: boolean;
  shape_params?: string[] | null;
  /** RADD-1329: no output ports at all. */
  terminal: boolean;
  /** FIXED ports; empty = params-dependent (`dynamic_ports`). Never fall back to the kind's table:
   * that drew `ai.validate` with TRUE/FALSE handles the engine never emits. */
  ports: string[];
  default_ports: string[];
  /** FIXED named outputs, on the same terms as `ports`. */
  outputs: OutputFieldInfo[];
  needs_items: boolean;
  permission: string;
}

/** A trigger kind (RADD-1323). `has_event: false` = there is no event to read
 * (a schedule, a manual run, a validation walk); `seeds` = the subjects a manual
 * run or dry run may start from. */
export interface TriggerKindInfo {
  key: string;
  label: string;
  group: string;
  description: string;
  params_schema: Record<string, unknown>;
  default_params: Record<string, unknown>;
  has_event: boolean;
  seeds: string[];
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

/** GET /automations/templates (RADD-1316): a whole automation offered as a
 * starting point. Opening one starts an unsaved, disabled draft. */
export interface AutomationTemplate {
  plugin: string;
  key: string;
  name: string;
  description: string;
  group: string;
  nodes: AutomationNode[];
  edges: AutomationEdge[];
}

/** GET /automations/catalog — everything the rule builder renders from. */
export interface AutomationCatalog {
  max_chain_depth: number;
  triggers: TriggerInfo[];
  operators: OperatorInfo[];
  manual_trigger: string;
  /** Spec 69: the "On a schedule" sentinel + the schedule kinds it offers. */
  schedule_trigger: string;
  schedule_kinds: { key: ScheduleKindValue; label: string }[];
  /** Every node type (RADD-1322). */
  nodes: NodeInfo[];
  /** Every trigger KIND (RADD-1323): the button, the clock, the draft check,
   * and any a plugin registers. */
  trigger_kinds: TriggerKindInfo[];
  /** How each node type reads its packet, built-in and contributed alike. */
  node_arity: NodeArityInfo[];
  /** `{{token}}` substitutions available in action text fields. Served so the
   * editor can SHOW what is supported instead of leaving people guessing. */
  tokens: { token: string; description: string; needs_item: boolean }[];
  /** Whether the CALLER may make an action run as someone else. The Act as
   * field is not rendered at all when false. */
  can_act_as: boolean;
}

/** The BUILT-IN actions, each an `action.<value>` node — a mirror of the backend `ActionType`. A
 * plugin's action (`action.send_email`, `release.publish`) is a catalog node this package never names. */
export const ActionType = {
  setState: "set_state",
  setPriority: "set_priority",
  setAssignee: "set_assignee",
  // Always per-item: "the next member" is a property of one issue.
  assignRoundRobin: "assign_round_robin",
  setTeam: "set_team",
  addLabel: "add_label",
  removeLabel: "remove_label",
  setCycle: "set_cycle",
  setRelease: "set_release",
  setCustomField: "set_custom_field",
  addComment: "add_comment",
  setParent: "set_parent",
  setType: "set_type",
  setReporter: "set_reporter",
  setDates: "set_dates",
  setEstimate: "set_estimate",
  setFlag: "set_flag",
  setVisibility: "set_visibility",
  linkItem: "link_item",
  archiveItem: "archive_item",
  addWatcher: "add_watcher",
  moveToProject: "move_to_project",
  // Universal actions (spec 58b) — run with or without a target item; their
  // text params accept {{event_type}}/{{actor.*}}/{{payload.*}}/{{item.*}}.
  createItem: "create_item",
  sendWebhook: "send_webhook",
  postChat: "post_chat",
  notifyUser: "notify_user",
} as const;
type ActionTypeValue = (typeof ActionType)[keyof typeof ActionType];

/** An action node's params in the `{type, params}` shape `ActionParams` edits (`type` without the
 * `action.` prefix). Names resolve per item at apply time; `"none"` clears. */
export interface RuleAction {
  type: ActionTypeValue;
  params: Record<string, ActionParamValue>;
}

/** Member-visible slice of an enabled manual rule — the `/` menu's custom actions. */
export interface RunnableRule {
  id: string;
  name: string;
}

// The graph (spec 116): a DAG of trigger / source / filter / gate / action nodes. `trigger` and
// `schedule` are not sent — the server derives them from the trigger nodes.

export const NodeKind = {
  trigger: "trigger",
  /** Produces items (the SLQ search node); every other kind can only narrow what it was handed. */
  source: "source",
  filter: "filter",
  gate: "gate",
  action: "action",
} as const;
export type NodeKindValue = (typeof NodeKind)[keyof typeof NodeKind];

/** How a node reads its packet: `set` once over the whole packet, `item` per item (a router then
 * partitions the set across its ports). There is no loop node. */
export const NodeArity = { set: "set", item: "item" } as const;
export type NodeArityValue = (typeof NodeArity)[keyof typeof NodeArity];

/** How one node type may read its packet; one option = fixed, no control. Served, never mirrored. */
export interface NodeArityInfo {
  type: string;
  default: NodeArityValue;
  options: NodeArityValue[];
}

/** What a search node does with the packet it was handed. */
export const SearchMode = { replace: "replace", add: "add" } as const;

/** Which way a graph's canvas flows. */
export type Orientation = "vertical" | "horizontal";

export interface AutomationNode {
  id: string;
  kind: NodeKindValue;
  /** The node-type key: "trigger.event", "filter.slq", "action.add_label", … */
  type: string;
  params: Record<string, unknown>;
  /** What downstream tokens call this node (`{{triage.priority}}`); separate from `id`, which edges wire to. */
  name?: string;
  /** Canvas position; absent = never placed, laid out from topology. Ignored by the engine. */
  x?: number | null;
  y?: number | null;
}

export interface AutomationEdge {
  source: string;
  /** Plain string: a contributed node names its own ports; the server checks them. */
  port: string;
  target: string;
}

/** One trigger node with its scheduler stamps — a list, since a graph may hold several. */
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
  orientation: Orientation;
  triggers: RuleTrigger[];
  /** The newest recorded run (RADD-1266); null/"" when it has never run or
   * its runs were swept. */
  last_run_at: string | null;
  last_run_status: string;
  /** The current version's number (RADD-1268). */
  version: number;
  created_at: string;
  updated_at: string;
}

/** One version of an automation (RADD-1268), as the history lists it. */
export interface AutomationVersion {
  id: string;
  automation_id: string;
  version: number;
  name: string;
  created_by_id: string | null;
  created_by_name: string;
  created_at: string;
  note: string;
  restored_from: number | null;
  node_count: number;
}

/** A version with its graph — what the read-only preview draws. */
export interface AutomationVersionDetail extends AutomationVersion {
  nodes: AutomationNode[];
  edges: AutomationEdge[];
  orientation: Orientation;
}

export interface RuleCreate {
  name: string;
  enabled?: boolean;
  position?: number;
  orientation?: Orientation;
  nodes: AutomationNode[];
  edges: AutomationEdge[];
  /** "Why" for the version this write makes (RADD-1268). */
  note?: string;
}

/** PATCH /automations/{id} — omitted keys untouched. The graph is replaced whole
 * or not at all: sending nodes without edges keeps the stored edges, and the
 * pair is re-validated together. */
export interface RuleUpdate {
  adopt_execution?: boolean;
  name?: string;
  enabled?: boolean;
  position?: number;
  orientation?: Orientation;
  nodes?: AutomationNode[];
  edges?: AutomationEdge[];
  /** "Why" for the version this write makes, if it makes one (RADD-1268). */
  note?: string;
}

/** One action's dry-run outcome (POST /automations/{id}/test). */
export interface ActionPreview {
  failed?: boolean;
  /** A built-in action's name, or a contributed node's full key (`script.run`). */
  type: string;
  params: Record<string, unknown>;
  /** False when a named target no longer resolves (the engine would skip it). */
  resolves: boolean;
  /** A workflow guard or the field registry refused it (RADD-1266). */
  refused: boolean;
  detail: string;
  /** Which node planned it, against which item — a graph runs the same action
   * type from several nodes, and once per item at per-item arity. */
  node_id: string;
  item_key: string;
  /** `{{token}}` -> what it rendered to. Only params that CARRIED a token
   * appear; when `resolves` is false, this is what `detail` is about. */
  resolved: Record<string, string>;
}

/** A value a node produced on a dry run, with the token that reads it. */
interface ProducedVar {
  token: string;
  name: string;
  value: string;
}

/** What left one port of one node on a dry run. */
interface PortResult {
  port: string;
  /** Exact, even when `sample` is capped. */
  count: number;
  /** Item keys — a sample you can recognise, which a count cannot be. */
  sample: string[];
  /** False = port not emitted at all (a gate's untaken branch) — not a filter emitting zero. */
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
  /** Validation graphs only (spec 119); empty otherwise. */
  findings: Finding[];
}

// Intake validation (spec 119).

/** `field` is a builtin name or `cf.<key>`; empty = about the submission as a whole. */
export interface Finding {
  message: string;
  field: string;
  /** The check that produced it; not shown. */
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
  /** Whether these findings REFUSE creation (server `verdict.blocks`; what makes `commit: "always"` 409).
   * Gate "create anyway" on this, never on `mode === "required"`: a required and an advisory graph can
   * govern one draft while only the advisory one trips. */
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
interface PayloadPathInfo {
  path: string;
  examples: string[];
  /** Inside a list — a template reading it may render several values, joined. */
  repeated: boolean;
}

/** GET /automations/samples/events. `sampled: 0` = never fired here; the UI says so, never invents a shape. */
export interface EventSample {
  event_type: string;
  sampled: number;
  paths: PayloadPathInfo[];
  /** Field names seen in `changes` diffs — what "field changed" can test. */
  changed_fields: string[];
  example: Record<string, unknown> | null;
  /** Entity types the event is about; each resolves as a canonical ref under its own key, fired or not. */
  subjects: string[];
  /** The event's own DECLARED shape, beyond the refs. Present even when
   * `sampled` is 0 — sampling says what has happened, declaration what will. */
  declared_schema: Record<string, unknown>;
  /** Paths the event DECLARES — served before anything has been sampled. */
  declared_paths: PayloadPathInfo[];
}

/** How a recorded run ended (mirror of the server's RunStatus, RADD-1266). */
export const RunStatus = {
  applied: "applied",
  nothingToDo: "nothing_to_do",
  refused: "refused",
  failed: "failed",
} as const;
type RunStatusValue = (typeof RunStatus)[keyof typeof RunStatus];

/** One recorded run, as `GET /automations/{id}/runs` lists it. */
export interface AutomationRun {
  id: string;
  automation_id: string;
  trigger_node_id: string;
  source: "event" | "schedule" | "manual";
  event_id: number | null;
  event_type: string;
  started_at: string;
  finished_at: string;
  status: RunStatusValue;
  actor_id: string | null;
  item_keys: string[];
  actions_applied: number;
  actions_skipped: number;
  error: string;
}

/** A run with its whole report — the dry run's shape. */
export interface AutomationRunDetail extends AutomationRun {
  report: RuleTestResult | null;
}
