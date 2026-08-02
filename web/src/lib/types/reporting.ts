/** Reporting (spec 19) — analytics response schemas. */
import type { StateCategoryValue } from "./workflow";
// ---------------------------------------------------------------------------
// Reporting (spec 19 — GET /reports/*). Analytics are computed on the fly from
// the event log; these mirror the reporting module's response schemas.
// ---------------------------------------------------------------------------

/** Bucket width for the time-series reports (throughput, cumulative flow). */
export const ReportInterval = {
  day: "day",
  week: "week",
} as const;
export type ReportIntervalValue = (typeof ReportInterval)[keyof typeof ReportInterval];

/** What velocity/burnup count (spec 70): items, or story-point sums. */
export const ReportMeasure = {
  count: "count",
  points: "points",
} as const;
export type ReportMeasureValue = (typeof ReportMeasure)[keyof typeof ReportMeasure];

/** One bucket of GET /reports/throughput — items that ENTERED a done state in it. */
export interface ThroughputBucket {
  /** ISO date labelling the bucket (its first day). */
  bucket: string;
  count: number;
}

/** One bucket of GET /reports/cumulative-flow — the category mix at bucket end. */
export interface CumulativeFlowBucket {
  bucket: string;
  /** StateCategory value → number of items sitting in it. */
  counts: Record<StateCategoryValue, number>;
}

/** One row of GET /reports/time-in-state — completed stays in a category. */
export interface TimeInStateRow {
  category: StateCategoryValue;
  avg_hours: number;
  median_hours: number;
  sample: number;
}

/** Compact cycle ref carried by a velocity row. */
export interface CycleBrief {
  id: string;
  name: string;
}

/** One row of GET /reports/velocity — items completed in a finished cycle. */
export interface VelocityRow {
  cycle: CycleBrief;
  completed: number;
}

/** The cycle window a burnup series ranges over. */
export interface CycleWindow {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
}

/** One day of a burnup: scope (items in the cycle) vs completed to date. */
export interface BurnupPoint {
  date: string;
  scope: number;
  completed: number;
}

/** GET /reports/burnup — daily scope vs completed over a cycle's window. */
export interface BurnupSeries {
  cycle: CycleWindow;
  series: BurnupPoint[];
}
