/** Reporting/timesheet windows, report staleness, and batch caps (specs 19/22/63/64/76/78). */

/** Default reporting window: throughput/CFD default to the last N days (spec 19). */
export const REPORT_DEFAULT_RANGE_DAYS = 56;

/** Report queries go stale after a minute (spec 75) — dashboard widgets and the
 * reports pages refetch on mount past that, never per-render. */
export const REPORT_STALE_MS = 60_000;

/** Timesheet report period (spec 22) — the anchor date resolves to a day/week/month window. */
export const TimesheetPeriod = {
  day: "day",
  week: "week",
  month: "month",
} as const;
export type TimesheetPeriodValue = (typeof TimesheetPeriod)[keyof typeof TimesheetPeriod];

/** How the timesheet grid groups its rows (spec 22; category added by spec 59). */
export const TimesheetGroupBy = {
  issue: "issue",
  epic: "epic",
  person: "person",
  category: "category",
} as const;
export type TimesheetGroupByValue = (typeof TimesheetGroupBy)[keyof typeof TimesheetGroupBy];

/** How many recent finished cycles the velocity control can request (backend caps at 50). */
export const VELOCITY_LAST_OPTIONS: readonly number[] = [3, 5, 8, 12];
export const VELOCITY_DEFAULT_LAST = 5;

/** SLA report window in weeks (spec 63; backend caps at 26). */
export const SLA_REPORT_WEEKS_OPTIONS: readonly number[] = [4, 8, 12, 26];
export const SLA_REPORT_DEFAULT_WEEKS = 12;
/** List/board SLA chips re-poll cadence — timers tick server-side (spec 63). */
export const SLA_BATCH_REFETCH_MS = 60_000;
/** Backend cap on one batch request — surfaces slice their visible ids to it. */
export const SLA_BATCH_MAX_ITEMS = 200;
/** Backend cap on one POST /items/rollup batch (spec 76). */
export const ROLLUP_MAX_ITEMS = 200;
/** Backend cap on one POST /items/timelog/batch (spec 78). */
export const TIMELOG_BATCH_MAX_ITEMS = 200;

/** Sidebar queue-badge counts re-poll cadence (spec 64). */
export const VIEW_COUNTS_REFETCH_MS = 60_000;
/** Backend cap on one POST /views/counts batch (spec 64). */
export const VIEW_COUNTS_MAX_VIEWS = 50;
