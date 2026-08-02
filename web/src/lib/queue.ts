import type { Item, SlaBatchResponse, SlaBatchTimer } from "./types";

/**
 * Queue-view helpers (spec 64): the age column format and the default
 * client-side urgency ordering — pure, over the loaded page only (server-side
 * SLA ordering needs due-time indexing; spec 30's known deferral stands).
 */

/** Compact item age for the queue's age column: "35m" / "5h" / "3d". */
export function formatAge(createdAt: string, now: Date = new Date()): string {
  const minutes = Math.max(0, Math.floor((now.getTime() - new Date(createdAt).getTime()) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

/** An item's urgency facts: any OPEN breach, and its earliest open due time.
 *  Met timers are settled — they don't drive triage order. */
function urgencyKey(timers: SlaBatchTimer[] | undefined): { breached: boolean; due: number } {
  let breached = false;
  let due = Number.POSITIVE_INFINITY;
  for (const timer of timers ?? []) {
    if (timer.met_at) continue;
    if (timer.breached) breached = true;
    if (timer.due_at) due = Math.min(due, new Date(timer.due_at).getTime());
  }
  return { breached, due };
}

/**
 * Default queue ordering (spec 64), applied over the loaded page when the
 * view's SLQ has NO explicit ORDER BY: open breaches first, then ascending
 * SLA due time (no-SLA items last), then oldest created.
 */
export function orderBySlaUrgency(
  items: Item[],
  slaByItem: SlaBatchResponse | undefined,
): Item[] {
  return items
    .map((item) => ({ item, key: urgencyKey(slaByItem?.[item.id]) }))
    .sort((a, b) => {
      if (a.key.breached !== b.key.breached) return a.key.breached ? -1 : 1;
      if (a.key.due !== b.key.due) return a.key.due - b.key.due;
      return a.item.created_at.localeCompare(b.item.created_at);
    })
    .map((entry) => entry.item);
}
