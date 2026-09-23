import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { CHART_ACCENT_COLOR } from "../../lib/meta";
import { throughputQuery } from "../../lib/queries";
import type { ReportIntervalValue } from "../../lib/types";
import { BarChart } from "../charts/BarChart";
import { ReportCard } from "../charts/ReportCard";
import { shortDate } from "../charts/chart-utils";
import { CardBody } from "./report-state";

/** Throughput: items entering a done state per bucket, as a bar chart (spec 19). */
export function ThroughputCard({
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
  const query = useQuery(throughputQuery(projectId, start, end, interval, q));
  const data = (query.data ?? []).map((bucket) => ({
    label: shortDate(bucket.bucket),
    value: bucket.count,
    title: `${bucket.bucket}: ${bucket.count} completed`,
  }));
  const total = (query.data ?? []).reduce((sum, bucket) => sum + bucket.count, 0);

  return (
    <ReportCard
      title="Throughput"
      description={`Issues completed per ${interval} — ${total} in range`}
    >
      <CardBody
        pending={query.isPending}
        error={query.isError ? errorMessage(query.error) : null}
        empty={total === 0}
        emptyMessage="No issues completed in this range."
      >
        <BarChart data={data} color={CHART_ACCENT_COLOR} ariaLabel="Throughput per bucket" />
      </CardBody>
    </ReportCard>
  );
}
