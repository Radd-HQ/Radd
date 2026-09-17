import { useStableItemBatches } from "../../lib/useStableItemBatches";
import { useQueries } from "@tanstack/react-query";
import { slaBatchQuery } from "../../lib/queries";
import type { SlaBatchResponse, SlaBatchTimer } from "../../lib/types";

/**
 * SLA timer chips (specs 30/63) — the shared rendering for the issue rail's
 * per-timer rows and the list/board "sla" card slot (nearest-to-breach chip
 * fed by POST /items/sla/batch).
 */

/** The states a chip renders — both ItemSla timers and batch timers fit. */
interface TimerLike {
  met_at: string | null;
  breached: boolean;
  paused: boolean;
  remaining_seconds: number | null;
}

export function formatRemaining(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes}m left`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${minutes % 60}m left`;
  return `${Math.floor(hours / 24)}d left`;
}

/** Countdown / Paused / Breached / Met / Met late pill (spec 30 rail states). */
export function SlaTimerChip({ timer, className = "" }: { timer: TimerLike; className?: string }) {
  const base = "rounded px-1.5 py-px text-[10px] font-medium " + className;
  if (timer.met_at) {
    return timer.breached ? (
      <span className={base + " bg-amber-500/15 text-amber-300"}>Met late</span>
    ) : (
      <span className={base + " bg-emerald-500/15 text-emerald-300"}>Met</span>
    );
  }
  if (timer.breached) {
    return <span className={base + " bg-red-500/15 text-red-300"}>Breached</span>;
  }
  if (timer.paused) {
    return <span className={base + " bg-strong/60 text-fg"}>Paused</span>;
  }
  return (
    <span className={base + " bg-accent/15 text-accent-text"}>
      {formatRemaining(timer.remaining_seconds)}
    </span>
  );
}

/** Urgency rank for the nearest-to-breach pick: open breach > ticking (fewest
 * seconds left) > paused > met late > met. */
function urgency(timer: SlaBatchTimer): number {
  if (timer.breached && !timer.met_at) return 0;
  if (timer.remaining_seconds !== null) return 1;
  if (timer.paused) return 2;
  if (timer.met_at && timer.breached) return 3;
  return 4;
}

export function nearestToBreach(timers: SlaBatchTimer[]): SlaBatchTimer | null {
  let nearest: SlaBatchTimer | null = null;
  for (const timer of timers) {
    if (
      nearest === null ||
      urgency(timer) < urgency(nearest) ||
      (urgency(timer) === urgency(nearest) &&
        timer.remaining_seconds !== null &&
        nearest.remaining_seconds !== null &&
        timer.remaining_seconds < nearest.remaining_seconds)
    ) {
      nearest = timer;
    }
  }
  return nearest;
}

/** The list/board slot chip: the item's most urgent timer, or nothing. */
export function SlaRowChip({ timers }: { timers: SlaBatchTimer[] | undefined }) {
  const timer = timers ? nearestToBreach(timers) : null;
  if (!timer) return null;
  return (
    <span title={`${timer.policy_name} · ${timer.kind} SLA`} className="inline-flex shrink-0">
      <SlaTimerChip timer={timer} />
    </span>
  );
}

/**
 * One batch call per loaded page (spec 63): keyed on the visible item ids,
 * re-polled every minute. `enabled=false` (slot off / nothing visible) fetches
 * nothing and returns undefined.
 */
export function useSlaBatch(itemIds: string[], enabled: boolean): SlaBatchResponse | undefined {
  const batches = useStableItemBatches(enabled ? itemIds : []);
  const queries = useQueries({queries: batches.map(ids => ({...slaBatchQuery(ids), }))});
  if (!enabled) return undefined;
  return Object.assign({}, ...queries.map(q => q.data ?? {})) as SlaBatchResponse;
}
