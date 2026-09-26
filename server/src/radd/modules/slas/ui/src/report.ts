import { queryOptions } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";
import type { ReportScope } from "@radd-plugin-ui/reporting/report-contract";

/** GET /sla-report — the slas plugin's own endpoint (RADD-1386; was reporting's /reports/sla). */
export const SLA_REPORT_PATH = "/sla-report";

/** The window picker's choices, in ISO weeks; the server caps the window at 26. */
export const SLA_REPORT_WEEKS_OPTIONS: readonly number[] = [4, 8, 12, 26];
export const SLA_REPORT_DEFAULT_WEEKS = 12;

/** A report goes stale after a minute, like the host's own reports. */
const SLA_REPORT_STALE_MS = 60_000;

/** The csat plugin: its ratings are on the report only while it is loaded (a weak edge). */
export const CSAT_PLUGIN = "csat";

/** The dashboard widget type this plugin renders (a builtin dashboards type; slas draws it). */
export const SLA_WIDGET_TYPE = "report_sla";

/** A `report_sla` widget's stored config. */
export interface SlaWidgetConfig {
  project_id?: string | null;
  weeks?: number;
}

/** Weekly service-desk outcomes for items created in one ISO week (spec 63). */
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
  /** Spec 65 — by the week the RESPONSE arrived; None/0 while csat is not loaded. */
  csat_avg: number | null;
  csat_count: number;
}

/** The weekly buckets plus the projects they cover (RADD-789). */
export interface SlaReport {
  buckets: SlaReportBucket[];
  scope: ReportScope;
}

/** Keyed under the plugin's name, so disabling slas drops the cached report with it. */
export const slaReportQuery = (projectId: string | null, weeks: number, q?: string) =>
  queryOptions({
    queryKey: ["slas", "report", { projectId, weeks }, { q: q ?? "" }] as const,
    queryFn: ({ signal }) =>
      api.get<SlaReport>(SLA_REPORT_PATH, {
        signal,
        query: { project_id: projectId ?? undefined, weeks: String(weeks), q: q || undefined },
      }),
    staleTime: SLA_REPORT_STALE_MS,
  });
