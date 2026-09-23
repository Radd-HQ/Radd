import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { BURNUP_COMPLETED_COLOR, BURNUP_SCOPE_COLOR } from "../../lib/meta";
import { burnupQuery, defaultBurnupCycleQuery } from "../../lib/queries";
import {
  ReportMeasure,
  type ReportMeasureValue,
} from "../../lib/types";
import { ChartLegend } from "../charts/ChartLegend";
import { LineChart } from "../charts/LineChart";
import { ReportCard } from "../charts/ReportCard";
import { CycleSelect } from "../cycles/CycleSelect";
import { shortDate } from "../charts/chart-utils";
import { CardBody, ScopeNote, Segmented } from "./report-state";
import { MEASURE_OPTIONS } from "./measure";

/** Burnup: daily scope vs completed (items or points, spec 70) for a chosen cycle. */
export function BurnupCard({
  showPoints,
  fixedCycleId,
  initialMeasure,
  q,
  projectId,
}: {
  /** RADD-1291: on a project's Reports, default to and pick from its cycles. */
  projectId?: string;
  /** Story points enabled in scope (spec 70) — offers the Count/Points toggle. */
  showPoints?: boolean;
  /** Pin the chart to ONE cycle and hide the picker (spec 75 dashboard widgets). */
  fixedCycleId?: string;
  /** Extra SLQ ANDed into the item universe (dashboard-wide filter). */
  q?: string;
  initialMeasure?: ReportMeasureValue;
}) {
  const [picked, setPicked] = useState("");
  const defaultCycle = useQuery({ ...defaultBurnupCycleQuery(projectId), enabled: !fixedCycleId && !picked });
  const cycleId = fixedCycleId ?? (picked || defaultCycle.data?.[0]?.id || "");
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
      controls={<>
        {showPoints && <Segmented ariaLabel="Burnup measure" value={measure}
          options={MEASURE_OPTIONS} onChange={setMeasure} />}
        {!fixedCycleId && <CycleSelect value={cycleId} onChange={setPicked} projectId={projectId} datedOnly
          emptyLabel={null} size="sm" className="max-w-56" />}
      </>}
    >
      <CardBody
        pending={(!cycleId && defaultCycle.isPending) || (Boolean(cycleId) && query.isPending)}
        error={
          !cycleId && defaultCycle.isError
            ? errorMessage(defaultCycle.error)
            : query.isError
              ? errorMessage(query.error)
              : null
        }
        empty={!cycleId || series.length === 0}
        emptyMessage="No cycles to chart — create a cycle and assign issues to it."
      >
        {chart}
      </CardBody>
    </ReportCard>
  );
}
