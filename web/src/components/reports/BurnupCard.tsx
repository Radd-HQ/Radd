import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { BURNUP_COMPLETED_COLOR, BURNUP_SCOPE_COLOR, CYCLE_STATUS_META } from "../../lib/meta";
import { burnupQuery, cyclesQuery } from "../../lib/queries";
import {
  CycleStatus,
  ReportMeasure,
  type Cycle,
  type ReportMeasureValue,
} from "../../lib/types";
import { ChartLegend } from "../charts/ChartLegend";
import { LineChart } from "../charts/LineChart";
import { ReportCard } from "../charts/ReportCard";
import { Select } from "../Select";
import { shortDate } from "../charts/chart-utils";
import { CardBody, ScopeNote, Segmented } from "./report-state";
import { MEASURE_OPTIONS } from "./measure";

/** The cycle a burnup should default to: the active one, else the most recent. */
function defaultCycleId(cycles: Cycle[]): string {
  const active = cycles.find((cycle) => cycle.status === CycleStatus.active);
  if (active) return active.id;
  const byRecent = [...cycles].sort((a, b) =>
    (b.start_date ?? "").localeCompare(a.start_date ?? ""),
  );
  return byRecent[0]?.id ?? "";
}

/** Burnup: daily scope vs completed (items or points, spec 70) for a chosen cycle. */
export function BurnupCard({
  showPoints,
  fixedCycleId,
  initialMeasure,
  q,
}: {
  /** Story points enabled in scope (spec 70) — offers the Count/Points toggle. */
  showPoints?: boolean;
  /** Pin the chart to ONE cycle and hide the picker (spec 75 dashboard widgets). */
  fixedCycleId?: string;
  /** Extra SLQ ANDed into the item universe (dashboard-wide filter). */
  q?: string;
  initialMeasure?: ReportMeasureValue;
}) {
  const cycles = useQuery(cyclesQuery());
  const cycleList = useMemo(
    () =>
      (cycles.data ?? [])
        // A draft (dateless) cycle has no window to chart — burnup 409s on it.
        .filter((cycle) => cycle.start_date && cycle.end_date)
        .sort((a, b) => (b.start_date ?? "").localeCompare(a.start_date ?? "")),
    [cycles.data],
  );
  const [picked, setPicked] = useState("");
  const cycleId = fixedCycleId ?? (picked || defaultCycleId(cycleList));
  const [measure, setMeasure] = useState<ReportMeasureValue>(
    initialMeasure ?? ReportMeasure.count,
  );
  const effective = showPoints ? measure : ReportMeasure.count;

  const query = useQuery({ ...burnupQuery(cycleId, effective, q), enabled: Boolean(cycleId) });
  const series = query.data?.series ?? [];

  const chart = (
    <>
      <LineChart
        xLabels={series.map((point) => shortDate(point.date))}
        series={[
          { key: "scope", label: "Scope", color: BURNUP_SCOPE_COLOR, points: series.map((p) => p.scope) },
          {
            key: "completed",
            label: "Completed",
            color: BURNUP_COMPLETED_COLOR,
            points: series.map((p) => p.completed),
          },
        ]}
        ariaLabel="Burnup: scope vs completed"
      />
      <div className="mt-3">
        <ChartLegend
          entries={[
            { label: "Scope", color: BURNUP_SCOPE_COLOR },
            { label: "Completed", color: BURNUP_COMPLETED_COLOR },
          ]}
        />
      </div>
    </>
  );

  return (
    <ReportCard
      title="Burnup"
      description="Scope vs completed over a cycle's window"
      note={<ScopeNote scope={query.data?.scope} />}
      controls={
        cycleList.length > 0 && (
          <>
            {showPoints && (
              <Segmented
                ariaLabel="Burnup measure"
                value={measure}
                options={MEASURE_OPTIONS}
                onChange={setMeasure}
              />
            )}
            {/* A pinned cycle (spec 75 widgets) hides the picker. */}
            {!fixedCycleId && (
              <Select
                aria-label="Cycle"
                value={cycleId}
                onChange={setPicked}
                size="sm"
                className="max-w-56"
                options={cycleList.map((cycle) => ({
                  value: cycle.id,
                  label: `${cycle.name} · ${CYCLE_STATUS_META[cycle.status].label}`,
                }))}
              />
            )}
          </>
        )
      }
    >
      <CardBody
        pending={cycles.isPending || (Boolean(cycleId) && query.isPending)}
        error={
          cycles.isError
            ? errorMessage(cycles.error)
            : query.isError
              ? errorMessage(query.error)
              : null
        }
        empty={cycleList.length === 0 || series.length === 0}
        emptyMessage="No cycles to chart — create a cycle and assign items to it."
      >
        {chart}
      </CardBody>
    </ReportCard>
  );
}
