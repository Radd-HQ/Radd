/** Service desk: canned responses, builtin-field write rules, rollups (specs 30/36/76/78). SLA
 * policies, timers and queues are the slas plugin's own (RADD-1394/1396). */
// ---------------------------------------------------------------------------
// Service desk (the canned module — spec 30)
// ---------------------------------------------------------------------------

export interface CannedResponse {
  id: string;
  title: string;
  body: string;
  position: number;
  created_at: string;
  updated_at: string;
}

/** GET /canned-responses/{id}/render?item_id= (spec 66) — body with `{{token}}`
 * variables resolved against that item; unresolved tokens stay verbatim. */
export interface CannedRender {
  body: string;
}

/** GET /instance (+ /instance/login-options) — safe instance-level config
 * (specs 35/67): the work week plus the timelog day/week lengths that back
 * client-side duration formatting (see lib/duration.ts). */
export interface InstanceConfig {
  work_week_days: string[];
  timelog_hours_per_day: number;
  timelog_days_per_week: number;
  /** Spec 121: the principal rows' fixed ids (share subjects for "Anyone on the web"). */
  anyone_id?: string | null;
  signed_in_id?: string | null;
}

// ---------------------------------------------------------------------------
// Builtin-field write rules (spec 36)
// ---------------------------------------------------------------------------

/** Builtin item fields that can carry write rules — mirrors BuiltinItemField. */
export const BUILTIN_RULE_FIELDS = [
  "title",
  "description",
  "state",
  "priority",
  "assignee",
  "reporter",
  "team",
  "labels",
  "parent",
  "start_date",
  "target_date",
  "cycle",
  "release",
  "flagged",
  "estimate_points",
] as const;
export type BuiltinRuleField = (typeof BUILTIN_RULE_FIELDS)[number];

/** Structural row identifiers — write-restrictable only, never read-blanked
 * (spec 50; complement of the server's READ_RESTRICTABLE_BUILTINS). */
export const WRITE_ONLY_BUILTIN_FIELDS: ReadonlySet<BuiltinRuleField> = new Set([
  "title",
  "state",
  "priority",
]);

/** Epic-progress aggregates over ALL of one item's descendants (spec 76):
 * done = done/canceled-category states; time is zeros without timelogging. */
export interface ItemRollup {
  total: number;
  done: number;
  in_progress: number;
  points_total: number;
  points_done: number;
  /** RADD-1493: readable descendants by the project KEY they live in. */
  by_project: Record<string, number>;
  /** RADD-1493: descendants that exist but the viewer may not read — a count, a floor. */
  withheld: number;
  estimate_seconds: number;
  logged_seconds: number;
}

/** POST /items/rollup — readable requested items only (zeros = no children). */
export type RollupResponse = Record<string, ItemRollup>;

/** One item's raw seconds in the timelog batch (spec 78) — None/0 = no data. */
export interface ItemTimelogBatchEntry {
  estimate_seconds: number | null;
  logged_seconds: number;
}

/** POST /items/timelog/batch — readable requested items only (spec 78). */
export type TimelogBatchResponse = Record<string, ItemTimelogBatchEntry>;

