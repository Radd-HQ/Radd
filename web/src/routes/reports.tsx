import { useState } from "react";
import { useParams } from "@tanstack/react-router";
import { CalendarRange } from "lucide-react";
import { REPORT_DEFAULT_RANGE_DAYS } from "../lib/constants";
import { isoDaysAgo } from "../lib/dates";
import { useProjectByKey, usePointsEnabled } from "../lib/hooks";
import { REPORT_INTERVAL_LABELS, REPORT_INTERVAL_ORDER } from "../lib/meta";
import { ReportInterval, type ReportIntervalValue } from "../lib/types";
import { Spinner } from "../components/Spinner";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";
import { useSlqQueryState } from "../lib/slq-filter";
import { BurnupCard } from "../components/reports/BurnupCard";
import { CumulativeFlowCard } from "../components/reports/CumulativeFlowCard";
import { Segmented } from "../components/reports/report-state";
import { SlaCard } from "../components/reports/SlaCard";
import { ThroughputCard } from "../components/reports/ThroughputCard";
import { TimeInStateCard } from "../components/reports/TimeInStateCard";
import { VelocityCard } from "../components/reports/VelocityCard";

const INTERVAL_OPTIONS = REPORT_INTERVAL_ORDER.map((interval) => ({
  value: interval,
  label: REPORT_INTERVAL_LABELS[interval],
}));

const dateInputClasses =
  "h-7 rounded-md border border-subtle bg-surface px-1.5 text-xs text-fg " +
  "cursor-pointer focus:outline-2 focus:outline-offset-1 focus:outline-focus [color-scheme:dark]";

/**
 * Project reporting dashboard (spec 19): throughput, cumulative flow, time in
 * state, velocity, and a cycle burnup. Throughput + CFD share the date-range
 * and interval controls; the other cards own their own controls.
 */
export function ReportsPage() {
  const { projectKey = "" } = useParams({ strict: false });
  const { project } = useProjectByKey(projectKey);

  const [start, setStart] = useState(() => isoDaysAgo(REPORT_DEFAULT_RANGE_DAYS));
  const [end, setEnd] = useState(() => isoDaysAgo(0));
  const [interval, setInterval] = useState<ReportIntervalValue>(ReportInterval.week);
  // Story points (spec 70): the Count/Points toggles exist only where enabled.
  const pointsEnabled = usePointsEnabled(project?.id);
  // Page-wide SLQ filter (top-bar query): ANDs into every report's item
  // universe server-side — same seam as the dashboard-wide filter.
  const slqFilter = useSlqQueryState();
  const q = slqFilter.committed || undefined;

  if (project === undefined) {
    return <Spinner label="Loading reports…" />;
  }
  if (project === null) {
    return <div className="p-10 text-sm text-fg-muted">Project “{projectKey}” not found.</div>;
  }

  return (
    <div className="flex h-full flex-col">
      <TopBarQuery>
        <QueryBar
          filter={slqFilter}
          projectId={project.id}
          placeholder="Filter these reports with SLQ: type = Bug AND assignee = me"
        />
      </TopBarQuery>
      <header className="flex items-center gap-3 border-b border-subtle px-5 py-3">
        <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-fg">
          {project.key}
        </span>
        <h1 className="text-sm font-semibold text-heading">{project.name} · Reports</h1>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="space-y-4 px-6 py-5">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-subtle bg-surface/30 px-4 py-2.5">
            <CalendarRange size={14} className="text-fg-muted" aria-hidden />
            <span className="text-xs text-fg-muted">Throughput &amp; cumulative flow</span>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs text-fg-muted">
                From
                <input
                  type="date"
                  value={start}
                  max={end}
                  onChange={(event) => setStart(event.target.value)}
                  className={dateInputClasses}
                  aria-label="Range start"
                />
              </label>
              <label className="flex items-center gap-1.5 text-xs text-fg-muted">
                To
                <input
                  type="date"
                  value={end}
                  min={start}
                  onChange={(event) => setEnd(event.target.value)}
                  className={dateInputClasses}
                  aria-label="Range end"
                />
              </label>
              <Segmented
                ariaLabel="Bucket interval"
                value={interval}
                options={INTERVAL_OPTIONS}
                onChange={setInterval}
              />
            </div>
          </div>

          <ThroughputCard projectId={project.id} start={start} end={end} interval={interval} q={q} />
          <CumulativeFlowCard projectId={project.id} start={start} end={end} interval={interval} q={q} />
          <BurnupCard showPoints={pointsEnabled} q={q} projectId={project.id} />
          <div className="grid gap-4 lg:grid-cols-2">
            <TimeInStateCard projectId={project.id} q={q} />
            <VelocityCard showPoints={pointsEnabled} q={q} />
          </div>
          {/* Service desk (spec 63): weekly SLA outcomes for this project. */}
          <SlaCard projectId={project.id} q={q} />
        </div>
      </div>
    </div>
  );
}
