/** Roadmap planners: import-children (spec 78, as-is placement) and the even
 *  spread (RADD-1510) — the one layout verb since RADD-1514, when the
 *  estimate/dependency/assignee-aware auto-schedule went (the thread's "it
 *  means nothing scheduling wise"). */

import { shiftIsoDay } from "@radd/plugin-sdk";
import { ROADMAP_LEAF_SPAN_DAYS } from "../../../lib/constants";
import type { Item, ItemUpdate } from "../../../lib/types";
import { isoDaysBetween } from "./dates";
import { epicGrowPatch, type BlocksEdge, type RoadmapPlanPatch } from "./planning";

/**
 * Calendar-day duration for one child (spec 78): ceil(estimate / working day)
 * with a 1-day floor when an estimate exists, else the tray default span.
 */
export function durationDaysFromEstimate(
  estimateSeconds: number | null | undefined,
  hoursPerDay: number,
): number {
  if (!estimateSeconds || estimateSeconds <= 0 || hoursPerDay <= 0) {
    return ROADMAP_LEAF_SPAN_DAYS;
  }
  return Math.max(1, Math.ceil(estimateSeconds / (hoursPerDay * 3600)));
}

interface TopoOrder {
  /** The children in dependency-then-rank order. */
  order: Item[];
  /** Per child, the ids of the loaded children that block it. */
  blockersOf: ReadonlyMap<string, string[]>;
}

/**
 * Kahn topological order over the `blocks` edges among `children` (deduped
 * here; other endpoints and self-loops ignored) with rank (input-order)
 * tie-breaking — a cyclic remainder falls back to rank order. Shared by
 * auto-schedule and the spread, so both verbs read the same way.
 */
export function topoOrder(children: Item[], edges: BlocksEdge[]): TopoOrder {
  const ids = new Set(children.map((child) => child.id));
  const indegree = new Map<string, number>(children.map((child) => [child.id, 0]));
  const dependentsOf = new Map<string, string[]>();
  const blockersOf = new Map<string, string[]>();
  const seen = new Set<string>();
  for (const edge of edges) {
    const key = `${edge.sourceId}>${edge.targetId}`;
    if (seen.has(key)) continue;
    seen.add(key);
    if (!ids.has(edge.sourceId) || !ids.has(edge.targetId) || edge.sourceId === edge.targetId) {
      continue;
    }
    indegree.set(edge.targetId, (indegree.get(edge.targetId) ?? 0) + 1);
    dependentsOf.set(edge.sourceId, [...(dependentsOf.get(edge.sourceId) ?? []), edge.targetId]);
    blockersOf.set(edge.targetId, [...(blockersOf.get(edge.targetId) ?? []), edge.sourceId]);
  }

  // Sweep the rank-ordered list, placing every ready child, until a sweep
  // places nothing. Cycles never become ready — the remainder appends in
  // rank order.
  const order: Item[] = [];
  const placed = new Set<string>();
  let progressed = true;
  while (order.length < children.length && progressed) {
    progressed = false;
    for (const child of children) {
      if (placed.has(child.id) || (indegree.get(child.id) ?? 0) > 0) continue;
      placed.add(child.id);
      order.push(child);
      progressed = true;
      for (const dependent of dependentsOf.get(child.id) ?? []) {
        indegree.set(dependent, (indegree.get(dependent) ?? 0) - 1);
      }
    }
  }
  for (const child of children) {
    if (!placed.has(child.id)) order.push(child);
  }
  return { order, blockersOf };
}

/** Date-less children imported AS-IS with no estimate span a single day —
 *  the bar exists; sizing it is left to the user (or Spread). */
const ROADMAP_IMPORT_SPAN_DAYS = 1;

interface ImportChildrenPlan {
  /** Fill patches for children missing a date, then the epic's grow patch (if any). */
  patches: RoadmapPlanPatch[];
  /** How many children had a date filled in (drives the toast). */
  importedCount: number;
}

/**
 * "Bring children into roadmap" — the AS-IS verb: no reflow, no
 * serialization, no rank chain. Only MISSING dates fill: a start
 * gets the caller's anchor, clamped to an existing target (the server rejects
 * inverted spans); a target gets start + estimate days − 1, or
 * `ROADMAP_IMPORT_SPAN_DAYS`. The epic's OUTWARD-only grow patch over every
 * child's effective window is appended last.
 */
export function importChildrenPlan(
  children: Item[],
  epic: Item,
  anchorIso: string,
  durations: ReadonlyMap<string, number>,
): ImportChildrenPlan {
  const patches: RoadmapPlanPatch[] = [];
  let importedCount = 0;
  let minStart: string | null = null;
  let maxEnd: string | null = null;
  for (const child of children) {
    let start = child.start_date ?? null;
    let target = child.target_date ?? null;
    const patch: ItemUpdate = {};
    if (!start) {
      // ISO days compare lexicographically — never start after an existing target.
      start = target && target < anchorIso ? target : anchorIso;
      patch.start_date = start;
    }
    if (!target) {
      const duration = Math.max(1, durations.get(child.id) ?? ROADMAP_IMPORT_SPAN_DAYS);
      target = shiftIsoDay(start, duration - 1);
      patch.target_date = target;
    }
    if (patch.start_date !== undefined || patch.target_date !== undefined) {
      importedCount += 1;
      patches.push({ itemId: child.id, patch });
    }
    if (minStart === null || start < minStart) minStart = start;
    if (maxEnd === null || target > maxEnd) maxEnd = target;
  }
  if (importedCount === 0) return { patches: [], importedCount: 0 };
  if (minStart !== null && maxEnd !== null) {
    const grow = epicGrowPatch(epic, minStart, maxEnd);
    if (grow) patches.push({ itemId: epic.id, patch: grow });
  }
  return { patches, importedCount };
}

interface SpreadChildrenPlan {
  /** One date patch per child, in slot order. The epic is never patched. */
  patches: RoadmapPlanPatch[];
  spreadCount: number;
  /** Child ids in slot order — the spec-82 rank chain input, so a freshly
   *  spread epic reads top-to-bottom by date. */
  orderedIds: string[];
}

/**
 * "Spread children across the epic" (RADD-1510): a LAYOUT, not an estimate.
 * The epic's own window is cut into N equal back-to-back slots — `topoOrder`
 * where `blocks` edges exist, rank order otherwise — and child i takes slot
 * i, so the children tile the epic exactly. A window shorter than N days
 * degrades to one-day slots that overlap rather than refusing. The epic
 * itself is untouched; a date-less epic yields an empty plan (there is no
 * window to spread across — "Fit to children" or a drag gives it one).
 */
export function spreadChildrenPlan(
  children: Item[],
  edges: BlocksEdge[],
  epic: Item,
): SpreadChildrenPlan {
  const epicStart = epic.start_date;
  const epicTarget = epic.target_date;
  if (children.length === 0 || !epicStart || !epicTarget) {
    return { patches: [], spreadCount: 0, orderedIds: [] };
  }
  const { order } = topoOrder(children, edges);
  const totalDays = isoDaysBetween(epicStart, epicTarget) + 1;
  const slots = order.length;
  const patches = order.map((child, index) => {
    const from = Math.floor((index * totalDays) / slots);
    const to = Math.max(from, Math.floor(((index + 1) * totalDays) / slots) - 1);
    return {
      itemId: child.id,
      patch: { start_date: shiftIsoDay(epicStart, from), target_date: shiftIsoDay(epicStart, to) },
    };
  });
  return { patches, spreadCount: slots, orderedIds: order.map((child) => child.id) };
}
