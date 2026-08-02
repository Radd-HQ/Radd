/** Roadmap schedulers: estimate/dependency/assignee-aware auto-schedule + import-children (spec 78). */

import { ROADMAP_LEAF_SPAN_DAYS } from "../../../lib/constants";
import { ItemLinkType, type Item, type ItemUpdate } from "../../../lib/types";
import { shiftIso } from "./dates";
import type { RoadmapPlanPatch } from "./planning";

// ---------------------------------------------------------------------------
// Auto-schedule (spec 78): estimate/dependency/assignee-aware epic layout
// ---------------------------------------------------------------------------

/** `source` blocks `target` — an intra-epic dependency for the scheduler. */
export interface AutoScheduleEdge {
  sourceId: string;
  targetId: string;
}

/** The `blocks` edges among one epic's loaded children (scheduler input). */
export function intraEpicBlocksEdges(children: Item[]): AutoScheduleEdge[] {
  const ids = new Set(children.map((child) => child.id));
  const seen = new Set<string>();
  const edges: AutoScheduleEdge[] = [];
  const add = (sourceId: string, targetId: string) => {
    const key = `${sourceId}>${targetId}`;
    if (seen.has(key) || !ids.has(sourceId) || !ids.has(targetId)) return;
    seen.add(key);
    edges.push({ sourceId, targetId });
  };
  for (const child of children) {
    for (const link of child.links?.outgoing ?? []) {
      if (link.link_type === ItemLinkType.blocks) add(child.id, link.item.id);
    }
    for (const link of child.links?.incoming ?? []) {
      if (link.link_type === ItemLinkType.blocks) add(link.item.id, child.id);
    }
  }
  return edges;
}

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

export interface AutoSchedulePlan {
  /** Child date patches in schedule order, then the epic fit patch. */
  patches: RoadmapPlanPatch[];
  scheduledCount: number;
  /** Child ids in the plan's schedule order — the spec-82 rank chain input,
   *  so a freshly scheduled epic reads top-to-bottom by date. */
  orderedIds: string[];
}

/**
 * "Auto-schedule children" (spec 78 §4): Kahn topological order over the
 * intra-epic `blocks` edges with rank (input-order) tie-breaking — a cyclic
 * remainder falls back to rank order. Each child starts at
 * `max(anchor, blockers' end + 1d, same-assignee last end + 1d)`: different or
 * missing assignees parallelize freely, a shared assignee serializes in
 * topo-then-rank order. `end = start + duration − 1` (inclusive spans). The
 * epic's own fit-to-children patch (inward AND outward — this verb owns the
 * span) is appended last.
 */
export function autoSchedulePlan(
  children: Item[],
  edges: AutoScheduleEdge[],
  anchorIso: string,
  durations: ReadonlyMap<string, number>,
  epic: Item,
): AutoSchedulePlan {
  if (children.length === 0) return { patches: [], scheduledCount: 0, orderedIds: [] };
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

  // Kahn with rank tie-breaking: sweep the rank-ordered list, placing every
  // ready child, until a sweep places nothing. Cycles never become ready —
  // the remainder appends in rank order.
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

  const endOf = new Map<string, string>();
  const lastEndByAssignee = new Map<string, string>();
  const patches: RoadmapPlanPatch[] = [];
  let minStart: string | null = null;
  let maxEnd: string | null = null;
  for (const child of order) {
    let start = anchorIso;
    for (const blockerId of blockersOf.get(child.id) ?? []) {
      const blockerEnd = endOf.get(blockerId);
      if (!blockerEnd) continue; // cycle fallback — the blocker isn't placed yet
      const candidate = shiftIso(blockerEnd, 1);
      if (candidate > start) start = candidate;
    }
    const assigneeId = child.assignee?.id ?? null;
    if (assigneeId) {
      const lastEnd = lastEndByAssignee.get(assigneeId);
      if (lastEnd) {
        const candidate = shiftIso(lastEnd, 1);
        if (candidate > start) start = candidate;
      }
    }
    const duration = Math.max(1, durations.get(child.id) ?? ROADMAP_LEAF_SPAN_DAYS);
    const end = shiftIso(start, duration - 1);
    endOf.set(child.id, end);
    if (assigneeId) lastEndByAssignee.set(assigneeId, end);
    patches.push({ itemId: child.id, patch: { start_date: start, target_date: end } });
    if (minStart === null || start < minStart) minStart = start;
    if (maxEnd === null || end > maxEnd) maxEnd = end;
  }
  if (minStart !== null && maxEnd !== null) {
    patches.push({ itemId: epic.id, patch: { start_date: minStart, target_date: maxEnd } });
  }
  return { patches, scheduledCount: order.length, orderedIds: order.map((child) => child.id) };
}

/** Date-less children imported AS-IS with no estimate span a single day —
 *  the bar exists; sizing it is left to the user (or Auto-schedule). */
export const ROADMAP_IMPORT_SPAN_DAYS = 1;

export interface ImportChildrenPlan {
  /** Fill patches for children missing a date, then the epic fit patch. */
  patches: RoadmapPlanPatch[];
  /** How many children had a date filled in (drives the toast). */
  importedCount: number;
}

/**
 * "Bring children into roadmap" — the AS-IS counterpart to `autoSchedulePlan`:
 * no reflow, no topo/assignee serialization, no rank chain. Children that
 * already have BOTH dates are untouched. A missing start fills with the epic
 * anchor (`epic.start ?? today`, resolved by the caller — the same anchor rule
 * the auto-scheduler uses), clamped back to the child's existing target when
 * there is one (the server rejects inverted spans). A missing target fills
 * with `start + duration − 1` (inclusive spans — 1 day means target == start)
 * anchored at the child's EFFECTIVE start; `durations` carries the
 * estimate-derived day counts and children absent from it (no estimate) span
 * `ROADMAP_IMPORT_SPAN_DAYS`. The epic's fit-to-children patch (inward AND
 * outward — this verb owns the span, like Auto-schedule) is appended last,
 * unioned over EVERY child's effective window. Nothing missing → an empty
 * plan (the menu disables the verb then anyway).
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
      target = shiftIso(start, duration - 1);
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
    patches.push({ itemId: epic.id, patch: { start_date: minStart, target_date: maxEnd } });
  }
  return { patches, importedCount };
}
