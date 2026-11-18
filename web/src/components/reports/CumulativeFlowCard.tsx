import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { CATEGORY_CHART_COLORS, CATEGORY_META, CATEGORY_ORDER } from "../../lib/meta";
import { cumulativeFlowQuery } from "../../lib/queries";
import { StateCategory, type ReportIntervalValue } from "../../lib/types";
import { CardBody, ChartLegend, ReportCard, StackedBarChart, type StackedBar } from "@radd-plugin-ui/reporting/charts";
import { shortDate } from "@radd/plugin-sdk";

const DONE = StateCategory.done;
/** Done starts hidden when it is more than this share of the newest bucket. */
const DONE_DOMINATES = 0.8;
const HIDDEN_KEY = "radd.reports.cumulativeFlow.hidden";

function readHidden(): string[] | null {
  try {
    const raw = localStorage.getItem(HIDDEN_KEY);
    return raw ? (JSON.parse(raw) as string[]) : null;
  } catch {
    return null;
  }
}

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

  // Which categories are drawn (RADD-1557). A project's Done pile dwarfs the
  // open work the chart is read for (85,000 against 15,000 on the perf seed),
  // so each legend entry toggles its series; the choice is remembered, and
  // until someone makes one, Done starts hidden when it dominates.
  const [stored, setStored] = useState<string[] | null>(readHidden);
  const latest: Record<string, number> = buckets.at(-1)?.counts ?? {};
  const latestTotal = Object.values(latest).reduce((sum, count) => sum + count, 0);
  const doneDominates = latestTotal > 0 && (latest[DONE] ?? 0) / latestTotal > DONE_DOMINATES;
  const hidden = new Set<string>(stored ?? (doneDominates ? [DONE] : []));
  const toggle = (category: string) => {
    const next = new Set(hidden);
    if (next.has(category)) next.delete(category);
    else next.add(category);
    setStored([...next]);
    try {
      localStorage.setItem(HIDDEN_KEY, JSON.stringify([...next]));
    } catch {
      // Best-effort: the choice still holds for this visit.
    }
  };

  const bars: StackedBar[] = buckets.map((bucket) => ({
    label: shortDate(bucket.bucket),
    segments: CATEGORY_ORDER.filter((category) => !hidden.has(category)).map((category) => ({
      key: category,
      label: CATEGORY_META[category].label,
      value: bucket.counts[category] ?? 0,
      color: CATEGORY_CHART_COLORS[category],
    })),
  }));

  // Legend for every category that appears in the window, hidden or not: a
  // hidden series has to stay reachable to be shown again.
  const present = CATEGORY_ORDER.filter((category) =>
    buckets.some((bucket) => (bucket.counts[category] ?? 0) > 0),
  );
  const legend = present.map((category) => ({
    label: CATEGORY_META[category].label,
    color: CATEGORY_CHART_COLORS[category],
    hidden: hidden.has(category),
    onToggle: () => toggle(category),
  }));
  const isEmpty = buckets.every((bucket) => Object.values(bucket.counts).every((count) => count === 0));
  const allHidden = !isEmpty && present.every((category) => hidden.has(category));

  return (
    <ReportCard title="Cumulative flow" description={`Issues by state category, per ${interval}`}>
      <CardBody
        pending={query.isPending}
        error={query.isError ? errorMessage(query.error) : null}
        empty={isEmpty}
        emptyMessage="No issue activity in this range."
      >
        {allHidden ? (
          <p className="py-10 text-center text-sm text-fg-muted">Every category is hidden. Pick one below.</p>
        ) : (
          <StackedBarChart bars={bars} ariaLabel="Cumulative flow by category" />
        )}
        <div className="mt-3">
          <ChartLegend entries={legend} />
        </div>
      </CardBody>
    </ReportCard>
  );
}
