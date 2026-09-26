import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage, SelectField, shortDate, Slot, useHasPlugin } from "@radd/plugin-sdk";
import {
  BAR_CHART_SLOT,
  CHART_LEGEND_SLOT,
  REPORT_CARD_SLOT,
  STACKED_BAR_CHART_SLOT,
  type StackedBar,
} from "@radd-plugin-ui/reporting/report-contract";
import {
  CSAT_PLUGIN,
  SLA_REPORT_DEFAULT_WEEKS,
  SLA_REPORT_WEEKS_OPTIONS,
  slaReportQuery,
  type SlaReportBucket,
} from "./report";

/** Met reads green and breached red, the traffic-light workflow colours; CSAT renders amber — the
 * star colour, which the warning fill is per theme (RADD-900). */
const MET_COLOR = "var(--status-success)";
const BREACHED_COLOR = "var(--status-danger)";
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
    <div className="rounded-lg border border-subtle bg-surface/40 px-3.5 py-2.5" data-sla-tile={label}>
      <p className="text-[11px] uppercase tracking-wide text-fg-muted">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-heading">{value}</p>
    </div>
  );
}

/**
 * Service desk SLA card (spec 63): summary tiles over the window (breach rate,
 * avg first response, avg resolution, CSAT while the csat plugin is loaded) + a
 * weekly met/breached trend, bucketed by the week each item was created.
 * Rendered on the reports pages and as the "Service desk SLA" dashboard widget.
 */
export function SlaReportCard({
  projectId,
  initialWeeks,
  q,
}: {
  projectId?: string;
  /** Starting window (spec 75 — dashboard widgets pin it from config). */
  initialWeeks?: number;
  /** Extra SLQ ANDed into the item universe (page- or dashboard-wide filter). */
  q?: string;
}) {
  const [weeks, setWeeks] = useState(initialWeeks ?? SLA_REPORT_DEFAULT_WEEKS);
  const query = useQuery(slaReportQuery(projectId ?? null, weeks, q));
  // RADD-1386: the server folds ratings in only while csat is loaded; say nothing about them otherwise.
  const csat = useHasPlugin(CSAT_PLUGIN);
  const buckets = query.data?.buckets ?? [];
  const window = totals(buckets);

  const bars: StackedBar[] = buckets.map((bucket) => ({
    label: shortDate(bucket.week),
    segments: [
      { key: "met", label: "Met", value: bucket.response_met + bucket.resolution_met, color: MET_COLOR },
      {
        key: "breached",
        label: "Breached",
        value: bucket.response_breached + bucket.resolution_breached,
        color: BREACHED_COLOR,
      },
    ],
  }));

  return (
    <div data-sla-report>
      <Slot
        id={REPORT_CARD_SLOT}
        title="Service desk"
        description="SLA targets met vs breached, by the week the issue was raised"
        scope={query.data?.scope}
        controls={
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Last
            <SelectField
              label=""
              ariaLabel="Report window in weeks"
              value={String(weeks)}
              onChange={(event) => setWeeks(Number(event.target.value))}
            >
              {SLA_REPORT_WEEKS_OPTIONS.map((option) => (
                <option key={option} value={String(option)}>
                  {option} weeks
                </option>
              ))}
            </SelectField>
          </label>
        }
        loading={query.isPending}
        error={query.isError ? errorMessage(query.error) : null}
        empty={window.items === 0 && window.csatCount === 0}
        emptyMessage="No SLA activity in this window — timers appear once a policy applies to issues."
      >
        <div className={`mb-4 grid gap-3 ${csat ? "grid-cols-4" : "grid-cols-3"}`}>
          <Tile label="Breach rate" value={`${Math.round(window.breachRate * 100)}%`} />
          <Tile label="Avg first response" value={formatSeconds(window.avgResponse)} />
          <Tile label="Avg resolution" value={formatSeconds(window.avgResolution)} />
          {csat && (
            <Tile
              label={`CSAT (${window.csatCount})`}
              value={window.csatAvg === null ? "—" : `${window.csatAvg.toFixed(1)} ★`}
            />
          )}
        </div>
        <Slot id={STACKED_BAR_CHART_SLOT} bars={bars} ariaLabel="SLA targets met vs breached per week" />
        <div className="mt-3">
          <Slot
            id={CHART_LEGEND_SLOT}
            entries={[
              { label: "Met", color: MET_COLOR },
              { label: "Breached", color: BREACHED_COLOR },
            ]}
          />
        </div>
        {csat && window.csatCount > 0 && (
          <div className="mt-5">
            <p className="mb-2 text-[11px] uppercase tracking-wide text-fg-muted">
              CSAT trend — avg rating by the week the response arrived
            </p>
            <Slot
              id={BAR_CHART_SLOT}
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
      </Slot>
    </div>
  );
}
