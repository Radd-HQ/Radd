import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { SLA_REPORT_DEFAULT_WEEKS, SLA_REPORT_WEEKS_OPTIONS } from "../../lib/constants";
import { SLA_BREACHED_COLOR, SLA_MET_COLOR } from "../../lib/meta";
import { slaReportQuery } from "../../lib/queries";
import type { SlaReportBucket } from "../../lib/types";
import { BarChart } from "../charts/BarChart";
import { ChartLegend } from "../charts/ChartLegend";
import { ReportCard } from "../charts/ReportCard";
import { Select } from "../Select";
import { StackedBarChart, type StackedBar } from "../charts/StackedBarChart";
import { shortDate } from "../charts/chart-utils";
import { CardBody, ScopeNote } from "./report-state";

/** CSAT (spec 65) renders amber — the star color, distinct from met/breached.
 * The warning fill IS star-amber per theme (RADD-900), so the bars follow the
 * theme instead of pinning dark-tuned amber-400 onto white. */
const CSAT_COLOR = "var(--status-warning)";

function formatSeconds(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

/** Weighted window totals from the weekly buckets (tiles over the whole range). */
function totals(buckets: SlaReportBucket[]) {
  const items = buckets.reduce((sum, bucket) => sum + bucket.items, 0);
  const breached = buckets.reduce(
    (sum, bucket) => sum + Math.round(bucket.breach_rate * bucket.items),
    0,
  );
  const weighted = (
    value: (bucket: SlaReportBucket) => number | null,
    count: (bucket: SlaReportBucket) => number,
  ) => {
    let total = 0;
    let samples = 0;
    for (const bucket of buckets) {
      const avg = value(bucket);
      if (avg === null) continue;
      total += avg * count(bucket);
      samples += count(bucket);
    }
    return samples > 0 ? total / samples : null;
  };
  const csatCount = buckets.reduce((sum, bucket) => sum + bucket.csat_count, 0);
  return {
    items,
    breachRate: items > 0 ? breached / items : 0,
    avgResponse: weighted((b) => b.avg_response_seconds, (b) => b.response_met),
    avgResolution: weighted((b) => b.avg_resolution_seconds, (b) => b.resolution_met),
    csatCount,
    csatAvg: weighted((b) => b.csat_avg, (b) => b.csat_count),
  };
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-subtle bg-surface/40 px-3.5 py-2.5">
      <p className="text-[11px] uppercase tracking-wide text-fg-muted">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-heading">{value}</p>
    </div>
  );
}

/**
 * Service desk SLA card (spec 63): summary tiles over the window (breach rate,
 * avg first response, avg resolution) + a weekly met/breached trend, bucketed
 * by the week each item was created.
 */
export function SlaCard({
  projectId,
  initialWeeks,
  q,
}: {
  projectId?: string;
  /** Starting window (spec 75 — dashboard widgets pin it from config). */
  initialWeeks?: number;
  /** Extra SLQ ANDed into the item universe (dashboard-wide filter). */
  q?: string;
}) {
  const [weeks, setWeeks] = useState(initialWeeks ?? SLA_REPORT_DEFAULT_WEEKS);
  const query = useQuery(slaReportQuery(projectId ?? null, weeks, q));
  // RADD-789: the buckets plus the projects they were computed over.
  const buckets = query.data?.buckets ?? [];
  const window = totals(buckets);

  const bars: StackedBar[] = buckets.map((bucket) => ({
    label: shortDate(bucket.week),
    segments: [
      {
        key: "met",
        label: "Met",
        value: bucket.response_met + bucket.resolution_met,
        color: SLA_MET_COLOR,
      },
      {
        key: "breached",
        label: "Breached",
        value: bucket.response_breached + bucket.resolution_breached,
        color: SLA_BREACHED_COLOR,
      },
    ],
  }));

  return (
    <ReportCard
      title="Service desk"
      description="SLA targets met vs breached, by the week the issue was raised"
      note={<ScopeNote scope={query.data?.scope} />}
      controls={
        <label className="flex items-center gap-1.5 text-xs text-fg-muted">
          Last
          <Select
            aria-label="Report window in weeks"
            value={String(weeks)}
            onChange={(value) => setWeeks(Number(value))}
            size="sm"
            options={SLA_REPORT_WEEKS_OPTIONS.map((option) => ({
              value: String(option),
              label: `${option} weeks`,
            }))}
          />
        </label>
      }
    >
      <CardBody
        pending={query.isPending}
        error={query.isError ? errorMessage(query.error) : null}
        empty={window.items === 0 && window.csatCount === 0}
        emptyMessage="No SLA activity in this window — timers appear once a policy applies to issues."
      >
        <div className="mb-4 grid grid-cols-4 gap-3">
          <Tile label="Breach rate" value={`${Math.round(window.breachRate * 100)}%`} />
          <Tile label="Avg first response" value={formatSeconds(window.avgResponse)} />
          <Tile label="Avg resolution" value={formatSeconds(window.avgResolution)} />
          <Tile
            label={`CSAT (${window.csatCount})`}
            value={window.csatAvg === null ? "—" : `${window.csatAvg.toFixed(1)} ★`}
          />
        </div>
        <StackedBarChart bars={bars} ariaLabel="SLA targets met vs breached per week" />
        <div className="mt-3">
          <ChartLegend
            entries={[
              { label: "Met", color: SLA_MET_COLOR },
              { label: "Breached", color: SLA_BREACHED_COLOR },
            ]}
          />
        </div>
        {window.csatCount > 0 && (
          <div className="mt-5">
            <p className="mb-2 text-[11px] uppercase tracking-wide text-fg-muted">
              CSAT trend — avg rating by the week the response arrived
            </p>
            <BarChart
              data={buckets.map((bucket) => ({
                label: shortDate(bucket.week),
                value: bucket.csat_avg ?? 0, // no responses = no bar
                title:
                  bucket.csat_avg === null
                    ? `${shortDate(bucket.week)}: no responses`
                    : `${shortDate(bucket.week)}: ${bucket.csat_avg.toFixed(1)} ★ (${bucket.csat_count})`,
              }))}
              color={CSAT_COLOR}
              height={140}
              ariaLabel="Average CSAT rating per week"
            />
          </div>
        )}
      </CardBody>
    </ReportCard>
  );
}
