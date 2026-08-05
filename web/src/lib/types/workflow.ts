/** Workflow states + transition enforcement (spec 61). */
// ---------------------------------------------------------------------------
// Workflow (states)
// ---------------------------------------------------------------------------

/** Fixed state categories (Linear model) — mirrors backend `StateCategory`. */
export const StateCategory = {
  triage: "triage",
  backlog: "backlog",
  todo: "todo",
  in_progress: "in_progress",
  done: "done",
  canceled: "canceled",
} as const;
export type StateCategoryValue = (typeof StateCategory)[keyof typeof StateCategory];

export interface State {
  id: string;
  project_id: string;
  name: string;
  category: StateCategoryValue;
  position: number;
  is_default: boolean;
  created_at: string;
  /** RADD-854: the vocabulary row classifying this state. */
  category_key: string;
}

export interface StateCreate {
  project_id: string;
  name: string;
  category: StateCategoryValue;
  position?: number | null;
}

/** PATCH /states/{id} — rename / reposition. */
export interface StateUpdate {
  name?: string;
  /** RADD-853/854: a category KEY (vocabulary row); the semantic behaviour
   *  derives from the row's behaves_as server-side. */
  category?: string;
  position?: number;
  /** RADD-852: null leaves the group; absent = untouched. */
  group_id?: string | null;
}

/** Embedded state on ItemRead. */
export interface StateRef {
  id: string;
  name: string;
  category: StateCategoryValue;
}

/** Workflow transition enforcement (spec 61) — the cascaded scalar setting. */
export const TransitionMode = {
  off: "off",
  guards: "guards",
  strict: "strict",
} as const;
export type TransitionModeValue = (typeof TransitionMode)[keyof typeof TransitionMode];

/** The scoped-settings key the mode select reads/writes (spec 50 cascade). */
export const WORKFLOW_TRANSITION_MODE_KEY = "workflow_transition_mode";

/** Validation rules a transition row may carry (spec 61; reshaped by spec 107:
 * every data check is one require_field condition; require_approval carries
 * per-entry approver rules). */
export const TransitionCheck = {
  requireField: "require_field",
  requireApproval: "require_approval",
} as const;
export type TransitionCheckValue = (typeof TransitionCheck)[keyof typeof TransitionCheck];

/** What a require_field condition addresses (spec 107). */
export const ConditionKind = { builtin: "builtin", custom: "custom" } as const;
export type ConditionKindValue = (typeof ConditionKind)[keyof typeof ConditionKind];

/** Operators a require_field condition may use (subset per field — spec 107). */
export const ConditionOp = {
  set: "set",
  empty: "empty",
  is: "is",
  isNot: "is_not",
  gte: "gte",
  lte: "lte",
} as const;
export type ConditionOpValue = (typeof ConditionOp)[keyof typeof ConditionOp];

export interface FieldConditionParams {
  kind: ConditionKindValue;
  key: string;
  op: ConditionOpValue;
  /** Registry type snapshot, custom fields only (server-set). */
  type?: string;
  values?: string[];
  /** Human names for id-valued `values` (failure strings only). */
  display?: string[];
}

/** One approver entry on a require_approval rule (spec 107): a user must
 * approve personally; a team needs `required` approvals from current members. */
export interface ApproverEntry {
  kind: "user" | "team";
  id: string;
  /** Display snapshot — the server re-resolves it on write. */
  name?: string;
  required?: number;
}

export type TransitionRule =
  | { check: typeof TransitionCheck.requireField; params: FieldConditionParams }
  | { check: typeof TransitionCheck.requireApproval; params: { approvers: ApproverEntry[] } };

/** GET /projects/{id}/transitions — one guarded edge of the transition graph.
 * `applies_when` (spec 107 follow-up) scopes WHICH items the row governs
 * (empty = every item); rows resolve FIRST-MATCH in list order. */
export interface Transition {
  id: string;
  project_id: string;
  from_state_id: string | null; // null = any source state (the wildcard)
  to_state_id: string;
  rules: TransitionRule[];
  applies_when: FieldConditionParams[];
  position: number;
  created_at: string;
}

export interface TransitionCreate {
  project_id: string;
  from_state_id?: string | null;
  to_state_id: string;
  rules?: TransitionRule[];
  applies_when?: FieldConditionParams[];
  position?: number;
}

/** PATCH /transitions/{id} — explicit `from_state_id: null` = the wildcard. */
export interface TransitionUpdate {
  from_state_id?: string | null;
  to_state_id?: string;
  rules?: TransitionRule[];
  applies_when?: FieldConditionParams[];
  position?: number;
}

/** GET /items/{id}/allowed-transitions — per-target allow/deny + failure list. */
export interface AllowedTarget {
  state_id: string;
  allowed: boolean;
  failures: string[];
}

export interface AllowedTransitions {
  mode: TransitionModeValue;
  targets: AllowedTarget[];
}

/** The user-owned category tier (RADD-854): vocabulary over fixed semantics. */
export interface StateCategoryRow {
  id: string;
  key: string;
  name: string;
  color: string | null;
  position: number;
  /** The semantic anchor — one of the six fixed StateCategory behaviours. */
  behaves_as: StateCategoryValue;
  is_builtin: boolean;
}
