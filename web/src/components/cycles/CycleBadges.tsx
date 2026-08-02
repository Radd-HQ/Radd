import { CalendarRange } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { shortDate } from "../../lib/dates";
import { CYCLE_STATUS_META } from "../../lib/meta";
import { cycleStatsQuery } from "../../lib/queries";
import type { CycleStats, CycleStatusValue } from "../../lib/types";

/** Pill/color atoms for cycle headers (group handles, the cycle page). */

export function CycleStatusPill({ status }: { status: CycleStatusValue }) {
  const meta = CYCLE_STATUS_META[status];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-px text-[11px] leading-4 ${meta.pillClassName}`}
    >
      <span className={`size-1.5 rounded-full ${meta.dotClassName}`} aria-hidden />
      {meta.label}
    </span>
  );
}

export function CycleDatesBadge({ start, end }: { start: string | null; end: string | null }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-fg-muted">
      <CalendarRange size={11} aria-hidden />
      {start && end ? `${shortDate(start)} – ${shortDate(end)}` : "Not scheduled"}
    </span>
  );
}

/** "2/3 done" — emerald once everything's finished, neutral while in flight. */
export function DoneCountPill({ done, total }: { done: number; total: number }) {
  const complete = total > 0 && done === total;
  return (
    <span
      className={
        "inline-flex shrink-0 items-center rounded-full border px-2 py-px text-[11px] leading-4 " +
        (complete
          ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
          : "border-strong bg-elevated/60 text-fg")
      }
    >
      {done}/{total} done
    </span>
  );
}

function TimeChip({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className: string;
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-px text-[11px] leading-4 ${className}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="font-medium">{value}</span>
    </span>
  );
}

/**
 * Compact cycle-wide time stats for a cycle handle/header — the same
 * estimate/logged/remaining chips (and server source) as the cycle page,
 * shown only once any time has been estimated or logged so empty cycles
 * keep a slim handle. Shared by cycle-axis view handles AND the standalone
 * planning page, so the two surfaces render cycles identically.
 */
export function CycleHeaderStats({
  cycleId,
  projectId,
}: {
  cycleId: string;
  /** REQUIRED on project-scoped surfaces: cycles span projects, so an unscoped
   * fetch would show other projects' time in this project's handle. */
  projectId?: string;
}) {
  const stats = useQuery(cycleStatsQuery(cycleId, undefined, undefined, projectId));
  const data = stats.data;
  if (!data || (!data.estimate_seconds && !data.logged_seconds && !data.remaining_seconds)) {
    return null;
  }
  return <CycleTimeChips stats={data} />;
}

/**
 * The estimate/logged/remaining trio as tinted chips — shared by the cycle
 * page header and the compact cycle group handles in lists.
 */
export function CycleTimeChips({ stats }: { stats: CycleStats }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <TimeChip
        label="Estimate"
        value={stats.estimate}
        className="border-accent-hover/30 bg-accent-hover/10 text-accent-text-strong"
      />
      <TimeChip
        label="Logged"
        value={stats.logged}
        className="border-chart-progress/40 bg-chart-progress/12 text-chart-progress-ink"
      />
      <TimeChip
        label="Remaining"
        value={stats.remaining}
        className={
          // Negative = over-logged (red); positive = time still on the clock
          // (amber); exactly zero = burned down clean (neutral).
          stats.remaining_seconds < 0
            ? "border-red-400/40 bg-red-400/10 text-red-300"
            : stats.remaining_seconds > 0
              ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
              : "border-strong bg-elevated/60 text-fg-secondary"
        }
      />
    </span>
  );
}
