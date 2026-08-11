/** Service desk: canned responses, SLA policies/timers, builtin-field write rules, rollups (specs 30/36/63/76/78). */
import type { PriorityValue } from "./items";
import type { ReportScope } from "./reporting";
// ---------------------------------------------------------------------------
// Service desk (canned + slas modules — spec 30)
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

export const SlaKind = {
  response: "response",
  resolution: "resolution",
} as const;
export type SlaKindValue = (typeof SlaKind)[keyof typeof SlaKind];

/** Project-level since spec 67 (instance-wide policies are retired). */
export interface SlaPolicy {
  id: string;
  project_id: string;
  name: string;
  enabled: boolean;
  response_minutes: number | null;
  resolution_minutes: number | null;
  pause_state_names: string[];
  /** Count only the instance work week — weekends pause the clock (spec 35). */
  work_week_only: boolean;
  /** Spec 63: priorities the policy applies to; [] = every priority. */
  priorities: PriorityValue[];
  /** RADD-1043: issue type ids the policy applies to; [] = every type. */
  issue_type_ids: string[];
  /** Spec 63: first-match resolution order (position, then created_at). */
  position: number;
  /** Spec 63: daily business-hours window, minutes from midnight (both or neither). */
  business_start_minute: number | null;
  business_end_minute: number | null;
  /** Spec 69: emit sla.due_soon when remaining time drops to this (null = off). */
  warning_minutes: number | null;
  created_at: string;
  updated_at: string;
}

/** GET /instance (+ /instance/login-options) — safe instance-level config
 * (specs 35/67): the work week plus the timelog day/week lengths that back
 * client-side duration formatting (see lib/duration.ts). */
export interface InstanceConfig {
  work_week_days: string[];
  timelog_hours_per_day: number;
  timelog_days_per_week: number;
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

export interface SlaTimer {
  kind: SlaKindValue;
  target_minutes: number;
  due_at: string | null;
  met_at: string | null;
  breached: boolean;
  paused: boolean;
  remaining_seconds: number | null;
}

export interface ItemSlaEntry {
  policy_id: string;
  policy_name: string;
  timers: SlaTimer[];
}

export interface ItemSla {
  entries: ItemSlaEntry[];
}

/** One timer of an item's MATCHED policy (spec 63 batch endpoint). */
export interface SlaBatchTimer {
  policy_name: string;
  kind: SlaKindValue;
  due_at: string | null;
  met_at: string | null;
  breached: boolean;
  paused: boolean;
  remaining_seconds: number | null;
}

/** POST /items/sla/batch — readable items with a matched policy only. */
export type SlaBatchResponse = Record<string, SlaBatchTimer[]>;

/** Epic-progress aggregates over ALL of one item's descendants (spec 76):
 * done = done/canceled-category states; time is zeros without timelogging. */
export interface ItemRollup {
  total: number;
  done: number;
  in_progress: number;
  points_total: number;
  points_done: number;
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

/** GET /reports/sla — weekly service-desk outcomes (spec 63). */
export interface SlaReportBucket {
  week: string;
  items: number;
  response_met: number;
  response_breached: number;
  resolution_met: number;
  resolution_breached: number;
  breach_rate: number;
  avg_response_seconds: number | null;
  avg_resolution_seconds: number | null;
  /** Spec 65 — bucketed by the week the RESPONSE arrived, not item creation. */
  csat_avg: number | null;
  csat_count: number;
}

/** GET /reports/sla — the weekly buckets plus the scope they cover (RADD-789). */
export interface SlaReport {
  buckets: SlaReportBucket[];
  scope: ReportScope;
}
