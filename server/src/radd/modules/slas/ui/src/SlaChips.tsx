import type { SlaBatchTimer, TimerState } from "./timers";

/**
 * SLA timer chips (specs 30/63): the rail's per-timer rows and the SLA column / card cell
 * (the nearest-to-breach chip). Status colours are the semantic status tier — the ink tier is
 * the one that holds 4.5:1 on its own tint in both themes.
 */

export function formatRemaining(seconds: number | null): string {
  if (seconds === null) return "—";
  const minutes = Math.max(0, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes}m left`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${minutes % 60}m left`;
  return `${Math.floor(hours / 24)}d left`;
}

/** What a timer reads as — the chip's text and its semantic state. */
export function timerStatus(timer: TimerState): { label: string; state: string; className: string } {
  if (timer.met_at) {
    return timer.breached
      ? { label: "Met late", state: "met-late", className: "bg-status-warning/15 text-status-warning-ink" }
      : { label: "Met", state: "met", className: "bg-status-success/15 text-status-success-ink" };
  }
  if (timer.breached) return { label: "Breached", state: "breached", className: "bg-status-danger/15 text-status-danger-ink" };
  if (timer.paused) return { label: "Paused", state: "paused", className: "bg-strong/60 text-fg" };
  return { label: formatRemaining(timer.remaining_seconds), state: "ticking", className: "bg-accent/15 text-accent-text" };
}

/** Countdown / Paused / Breached / Met / Met late pill (spec 30 rail states). */
export function SlaTimerChip({ timer, className = "" }: { timer: TimerState; className?: string }) {
  const status = timerStatus(timer);
  return (
    <span data-sla-chip={status.state} className={`rounded px-1.5 py-px text-[10px] font-medium ${status.className} ${className}`}>
      {status.label}
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

/** The column / card cell: the item's most urgent timer, or nothing. */
export function SlaRowChip({ timers }: { timers: SlaBatchTimer[] }) {
  const timer = nearestToBreach(timers);
  if (!timer) return null;
  return (
    <span title={`${timer.policy_name} · ${timer.kind} SLA`} className="inline-flex shrink-0" data-sla-cell>
      <SlaTimerChip timer={timer} />
    </span>
  );
}
