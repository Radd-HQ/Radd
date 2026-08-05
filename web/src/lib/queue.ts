import type { Item, SlaBatchResponse, SlaBatchTimer } from "./types";

/**
 * Queue-view helpers (spec 64): the default client-side urgency ordering —
 * pure, over the loaded page only (server-side SLA ordering needs due-time
 * indexing; spec 30's known deferral stands).
 */

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
