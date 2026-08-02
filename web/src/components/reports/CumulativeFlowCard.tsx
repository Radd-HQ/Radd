import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { CATEGORY_CHART_COLORS, CATEGORY_META, CATEGORY_ORDER } from "../../lib/meta";
import { cumulativeFlowQuery } from "../../lib/queries";
import type { ReportIntervalValue } from "../../lib/types";
import { ChartLegend } from "../charts/ChartLegend";
import { ReportCard } from "../charts/ReportCard";
import { StackedBarChart, type StackedBar } from "../charts/StackedBarChart";
import { shortDate } from "../charts/chart-utils";
import { CardBody } from "./report-state";

/** Cumulative flow: the category mix at each bucket's end, as stacked bars (spec 19). */
export function CumulativeFlowCard({
  projectId,
  start,
  end,
  interval,
  q,
}: {
  projectId: string;
  start: string;
  end: string;
  interval: ReportIntervalValue;
  /** Extra SLQ ANDed into the item universe (dashboard-wide filter). */
  q?: string;
}) {
  const query = useQuery(cumulativeFlowQuery(projectId, start, end, interval, q));
  const buckets = query.data ?? [];

  const bars: StackedBar[] = buckets.map((bucket) => ({
    label: shortDate(bucket.bucket),
    segments: CATEGORY_ORDER.map((category) => ({
      key: category,
      label: CATEGORY_META[category].label,
      value: bucket.counts[category] ?? 0,
      color: CATEGORY_CHART_COLORS[category],
    })),
  }));

  // Legend only for categories that actually appear in the window.
  const present = CATEGORY_ORDER.filter((category) =>
    buckets.some((bucket) => (bucket.counts[category] ?? 0) > 0),
  );
  const legend = present.map((category) => ({
    label: CATEGORY_META[category].label,
    color: CATEGORY_CHART_COLORS[category],
  }));
  const isEmpty = bars.every((bar) => bar.segments.every((segment) => segment.value === 0));

  return (
    <ReportCard title="Cumulative flow" description={`Items by state category, per ${interval}`}>
      <CardBody
        pending={query.isPending}
        error={query.isError ? errorMessage(query.error) : null}
        empty={isEmpty}
        emptyMessage="No item activity in this range."
      >
        <StackedBarChart bars={bars} ariaLabel="Cumulative flow by category" />
        <div className="mt-3">
          <ChartLegend entries={legend} />
        </div>
      </CardBody>
    </ReportCard>
  );
}
