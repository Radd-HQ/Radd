/** Workflow states + transition enforcement (spec 61). */
import type { ContributedTransitionRule } from "@radd-plugin-ui/workflow/transition-rule-contract";
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

/** The checks workflow evaluates itself (spec 61; reshaped by spec 107: every data
 * check is one require_field condition). Any other check is a plugin's (RADD-1383):
 * its editor arrives through the transition-rule slot and the host only carries it. */
export const TransitionCheck = {
  requireField: "require_field",
  requireResolvedThreads: "require_resolved_threads",
  // RADD-1285: the item has a release (named form of require_field release set).
  requireRelease: "require_release",
} as const;

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

/** A rule over one of workflow's own checks. */
export type OwnTransitionRule =
  | { check: typeof TransitionCheck.requireResolvedThreads; params: Record<string, never> }
  | { check: typeof TransitionCheck.requireRelease; params: Record<string, never> }
  | { check: typeof TransitionCheck.requireField; params: FieldConditionParams };

/** A stored rule: one of workflow's own, or a plugin's (opaque params — its editor owns them). */
export type TransitionRule = OwnTransitionRule | ContributedTransitionRule;

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
  /** RADD-1285: performed automatically when a release is published (needs a from state). */
  on_release: boolean;
  created_at: string;
}

export interface TransitionCreate {
  project_id: string;
  from_state_id?: string | null;
  to_state_id: string;
  rules?: TransitionRule[];
  applies_when?: FieldConditionParams[];
  position?: number;
  on_release?: boolean;
}

/** PATCH /transitions/{id} — explicit `from_state_id: null` = the wildcard. */
export interface TransitionUpdate {
  from_state_id?: string | null;
  to_state_id?: string;
  rules?: TransitionRule[];
  applies_when?: FieldConditionParams[];
  position?: number;
  on_release?: boolean;
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
