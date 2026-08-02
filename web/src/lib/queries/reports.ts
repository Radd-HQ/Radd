/** Reporting (spec 19) — read-only analytics. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiReportPath,
  REPORT_STALE_MS,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  BurnupSeries,
  CumulativeFlowBucket,
  ItemKindValue,
  ReportIntervalValue,
  ReportMeasureValue,
  SlaReportBucket,
  ThroughputBucket,
  TimeInStateRow,
  VelocityRow,
} from "../types";

// ---------------------------------------------------------------------------
// Reporting (spec 19) — read-only analytics; all require item.read in scope.
// Dates are ISO `YYYY-MM-DD`; omit to let the backend default to the last 30d.
// ---------------------------------------------------------------------------

/** Items entering a done state per bucket, over [start, end]. */
export const throughputQuery = (
  projectId: string,
  start: string,
  end: string,
  interval: ReportIntervalValue,
  q?: string,
) =>
  queryOptions({
    queryKey: queryKeys.reportThroughput(projectId, start, end, interval, q),
    queryFn: () =>
      api.get<ThroughputBucket[]>(ApiReportPath.throughput, {
        query: { project_id: projectId, start, end, interval, q: q || undefined },
      }),
    staleTime: REPORT_STALE_MS,
  });

/** Category distribution of items at each bucket's end, over [start, end]. */
export const cumulativeFlowQuery = (
  projectId: string,
  start: string,
  end: string,
  interval: ReportIntervalValue,
  q?: string,
) =>
  queryOptions({
    queryKey: queryKeys.reportCumulativeFlow(projectId, start, end, interval, q),
    queryFn: () =>
      api.get<CumulativeFlowBucket[]>(ApiReportPath.cumulativeFlow, {
        query: { project_id: projectId, start, end, interval, q: q || undefined },
      }),
    staleTime: REPORT_STALE_MS,
  });

/** Avg/median hours items spent in each category; optional `kind` filter. */
export const timeInStateQuery = (projectId: string, kind: ItemKindValue | null, q?: string) =>
  queryOptions({
    queryKey: queryKeys.reportTimeInState(projectId, kind, q),
    queryFn: () =>
      api.get<TimeInStateRow[]>(ApiReportPath.timeInState, {
        query: { project_id: projectId, kind: kind ?? undefined, q: q || undefined },
      }),
    staleTime: REPORT_STALE_MS,
  });

/** Completed counts (or point sums, spec 70) for the last N finished cycles. */
export const velocityQuery = (last: number, measure: ReportMeasureValue, q?: string) =>
  queryOptions({
    queryKey: queryKeys.reportVelocity(last, measure, q),
    queryFn: () =>
      api.get<VelocityRow[]>(ApiReportPath.velocity, {
        query: { last: String(last), measure, q: q || undefined },
      }),
    staleTime: REPORT_STALE_MS,
  });

/** Daily scope-vs-completed series (items or points, spec 70) for one cycle. */
export const burnupQuery = (cycleId: string, measure: ReportMeasureValue, q?: string) =>
  queryOptions({
    queryKey: queryKeys.reportBurnup(cycleId, measure, q),
    queryFn: () =>
      api.get<BurnupSeries>(ApiReportPath.burnup, {
        query: { cycle_id: cycleId, measure, q: q || undefined },
      }),
    staleTime: REPORT_STALE_MS,
  });

/** Weekly service-desk SLA outcomes (spec 63) — server-wide, optional project. */
export const slaReportQuery = (projectId: string | null, weeks: number, q?: string) =>
  queryOptions({
    queryKey: queryKeys.reportSla(projectId, weeks, q),
    queryFn: () =>
      api.get<SlaReportBucket[]>(ApiReportPath.sla, {
        query: { project_id: projectId ?? undefined, weeks: String(weeks), q: q || undefined },
      }),
    staleTime: REPORT_STALE_MS,
  });
