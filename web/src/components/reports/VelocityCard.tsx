import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorMessage } from "../../lib/api";
import { VELOCITY_DEFAULT_LAST, VELOCITY_LAST_OPTIONS } from "../../lib/constants";
import { CHART_ACCENT_COLOR } from "../../lib/meta";
import { velocityQuery } from "../../lib/queries";
import { ReportMeasure, type ReportMeasureValue } from "../../lib/types";
import { BarChart } from "../charts/BarChart";
import { ReportCard } from "../charts/ReportCard";
import { Select } from "../Select";
import { CardBody, ScopeNote, Segmented } from "./report-state";
import { MEASURE_OPTIONS } from "./measure";

/** Velocity: completed items (or story points, spec 70) per finished cycle. */
export function VelocityCard({
  showPoints,
  initialLast,
  initialMeasure,
  q,
}: {
  /** Story points enabled in scope (spec 70) — offers the Count/Points toggle. */
  showPoints?: boolean;
  /** Starting control values (spec 75 — dashboard widgets pin them from config). */
  initialLast?: number;
  initialMeasure?: ReportMeasureValue;
  /** Extra SLQ ANDed into the item universe (dashboard-wide filter). */
  q?: string;
}) {
  const [last, setLast] = useState(initialLast ?? VELOCITY_DEFAULT_LAST);
  const [measure, setMeasure] = useState<ReportMeasureValue>(
    initialMeasure ?? ReportMeasure.count,
  );
  const effective = showPoints ? measure : ReportMeasure.count;
  const inPoints = effective === ReportMeasure.points;
  const unit = inPoints ? "pts" : "completed";
  const query = useQuery(velocityQuery(last, effective, q));
  // Cross-project: cycles span projects, so the figure carries the scope it was
  // computed over (RADD-789) and the header states it when that is a subset.
  const rows = query.data?.rows ?? [];
  const data = rows.map((row) => ({
    label: row.cycle.name,
    value: row.completed,
    title: `${row.cycle.name}: ${row.completed} ${unit}`,
  }));
  const average =
    rows.length > 0
      ? Math.round((rows.reduce((sum, row) => sum + row.completed, 0) / rows.length) * 10) / 10
      : 0;

  return (
    <ReportCard
      title="Velocity"
      description={
        rows.length > 0
          ? `${inPoints ? "Points" : "Completed"} per cycle — avg ${average}`
          : "Completed issues per finished cycle"
      }
      note={<ScopeNote scope={query.data?.scope} />}
      controls={
        <>
          {showPoints && (
            <Segmented
              ariaLabel="Velocity measure"
              value={measure}
              options={MEASURE_OPTIONS}
              onChange={setMeasure}
            />
          )}
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Last
            <Select
              aria-label="Number of cycles"
              value={String(last)}
              onChange={(value) => setLast(Number(value))}
              size="sm"
              options={VELOCITY_LAST_OPTIONS.map((option) => ({
                value: String(option),
                label: String(option),
              }))}
            />
          </label>
        </>
      }
    >
      <CardBody
        pending={query.isPending}
        error={query.isError ? errorMessage(query.error) : null}
        empty={rows.length === 0}
        emptyMessage="No finished cycles yet — velocity appears once a cycle's end date has passed."
      >
        <BarChart data={data} color={CHART_ACCENT_COLOR} ariaLabel="Velocity per cycle" />
      </CardBody>
    </ReportCard>
  );
}
