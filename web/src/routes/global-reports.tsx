import { BarChart3 } from "lucide-react";
import { usePointsEnabled } from "../lib/hooks";
import { TopBarQuery } from "../components/shell/TopBarSlot";
import { QueryBar } from "../components/views/QueryBar";
import { useSlqQueryState } from "../lib/slq-filter";
import { BurnupCard } from "../components/reports/BurnupCard";
import { SlaCard } from "../components/reports/SlaCard";
import { VelocityCard } from "../components/reports/VelocityCard";

/**
 * Global reporting (spec 19): cross-cycle delivery — velocity across finished
 * cycles and a burnup for any chosen cycle. Project-scoped reports
 * (throughput, CFD, time-in-state) live on each project's Reports tab.
 */
export function GlobalReportsPage() {
  // Story points (spec 70): this page follows the INSTANCE-resolved default
  // (per-project overrides show on each project's own Reports tab).
  const pointsEnabled = usePointsEnabled();
  // Page-wide SLQ filter (top-bar query) — same seam as the dashboards.
  const slqFilter = useSlqQueryState();
  const q = slqFilter.committed || undefined;

  return (
    <div className="flex h-full flex-col">
      <TopBarQuery>
        <QueryBar
          filter={slqFilter}
          placeholder="Filter these reports with SLQ: team = Pipeline AND type = Bug"
        />
      </TopBarQuery>
      <header className="flex items-center gap-2.5 border-b border-subtle px-6 py-3.5">
        <BarChart3 size={16} className="text-fg-secondary" aria-hidden />
        <h1 className="text-sm font-semibold text-heading">Reports</h1>
        <span className="text-xs text-fg-muted">· delivery across all projects</span>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="space-y-4 px-6 py-5">
          <VelocityCard showPoints={pointsEnabled} q={q} />
          <BurnupCard showPoints={pointsEnabled} q={q} />
          {/* Service desk (spec 63): server-wide SLA outcomes. */}
          <SlaCard q={q} />
        </div>
      </div>
    </div>
  );
}
