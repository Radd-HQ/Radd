/** Roadmap edit planners: epic stretch, dependency cascade, epic container move (specs 77/78/81). */

import { ROADMAP_CASCADE_MAX_ITEMS } from "../../../lib/constants";
import { ItemLinkType, type Item, type ItemUpdate } from "../../../lib/types";
import { isoDaysBetween, isScheduled, shiftIso } from "./dates";
import type { RoadmapRow } from "./rows";

// ---------------------------------------------------------------------------
// Epic verbs (specs 77 + 78): outward stretch, fit to children, auto-schedule
// ---------------------------------------------------------------------------

/**
 * OUTWARD-only union patch for a parent epic after a child's move/resize
 * commit: widen whichever epic edge the child window now exceeds, never
 * shrink. Null when nothing needs stretching or the epic has no dates of its
 * own (derived spans track their children automatically). ISO `YYYY-MM-DD`
 * strings order lexicographically, so `<`/`>` compare calendar days.
 */
export function epicStretchPatch(
  epic: Item,
  childStartIso: string,
  childTargetIso: string,
): ItemUpdate | null {
  if (!isScheduled(epic)) return null;
  const patch: ItemUpdate = {};
  if (childStartIso < epic.start_date!) patch.start_date = childStartIso;
  if (childTargetIso > epic.target_date!) patch.target_date = childTargetIso;
  return patch.start_date !== undefined || patch.target_date !== undefined ? patch : null;
}

/** One planned date PATCH — `patch` carries only `start_date`/`target_date`. */
export interface RoadmapPlanPatch {
  itemId: string;
  patch: ItemUpdate;
}

/** A moved item's committed window (cascade + stretch-union inputs). */
export interface RoadmapMove {
  itemId: string;
  start: string;
  target: string;
}

/**
 * ONE outward-only stretch patch per parent epic covering EVERY moved child
 * (spec 78): unions the moved windows per epic FIRST, then applies
 * `epicStretchPatch` once — so a multi-item commit never issues two epic
 * patches that fight each other. Derived epics and epics that themselves moved
 * are skipped.
 */
export function epicStretchPatches(rows: RoadmapRow[], moves: RoadmapMove[]): RoadmapPlanPatch[] {
  const rowById = new Map(rows.map((row) => [row.item.id, row] as const));
  const movedIds = new Set(moves.map((move) => move.itemId));
  const unionByEpic = new Map<string, { start: string; target: string }>();
  for (const move of moves) {
    const epicId = rowById.get(move.itemId)?.parentEpicId;
    if (!epicId || movedIds.has(epicId)) continue;
    const epicRow = rowById.get(epicId);
    if (!epicRow || epicRow.derived) continue;
    const union = unionByEpic.get(epicId);
    if (!union) unionByEpic.set(epicId, { start: move.start, target: move.target });
    else {
      if (move.start < union.start) union.start = move.start;
      if (move.target > union.target) union.target = move.target;
    }
  }
  const patches: RoadmapPlanPatch[] = [];
  for (const [epicId, union] of unionByEpic) {
    const stretch = epicStretchPatch(rowById.get(epicId)!.item, union.start, union.target);
    if (stretch) patches.push({ itemId: epicId, patch: stretch });
  }
  return patches;
}

export interface CascadePlan {
  /** Dependent pushes first, then the deduped parent-epic stretches. The
   *  seed bars' own patches are NOT included — the caller commits them. */
  patches: RoadmapPlanPatch[];
  /** How many dependent items were pushed (drives the success toast). */
  cascadedCount: number;
  /** True when the cap tripped — commit only the gesture's own bars + warn. */
  truncated: boolean;
}

/**
 * Multi-seed dependency cascade (specs 78 + 81): after the gesture commits the
 * `seeds` (one bar for a plain drag, an epic + its children for a container
 * drag), BFS over `blocks` edges among the LOADED rows pushes every dependent
 * whose start is on/before its blocker's new target to `blocker.target + 1d`
 * (duration preserved), recursively against the working copy of spans.
 * Push-forward ONLY — moving a blocker earlier just grows slack. Seeds are
 * deduped and NEVER re-pushed: their spans are the user's statement, and the
 * moved set's relative layout stays intact. Fan-in re-pushes on cascaded items
 * take the max naturally. Capped at `ROADMAP_CASCADE_MAX_ITEMS` CASCADED items
 * (seeds don't count; beyond → `truncated`, empty patches). Parent-epic
 * outward stretches for every moved item ride along, union-deduped per epic
 * (epics that themselves moved are skipped inside `epicStretchPatches`).
 */
export function cascadePlanMulti(rows: RoadmapRow[], seeds: RoadmapMove[]): CascadePlan {
  const rowById = new Map(rows.map((row) => [row.item.id, row] as const));
  const dependents = new Map<string, Set<string>>();
  const addEdge = (blockerId: string, dependentId: string) => {
    if (!rowById.has(blockerId) || !rowById.has(dependentId)) return;
    const bucket = dependents.get(blockerId);
    if (bucket) bucket.add(dependentId);
    else dependents.set(blockerId, new Set([dependentId]));
  };
  for (const row of rows) {
    for (const link of row.item.links?.outgoing ?? []) {
      if (link.link_type === ItemLinkType.blocks) addEdge(row.item.id, link.item.id);
    }
    for (const link of row.item.links?.incoming ?? []) {
      if (link.link_type === ItemLinkType.blocks) addEdge(link.item.id, row.item.id);
    }
  }

  const truncated: CascadePlan = { patches: [], cascadedCount: 0, truncated: true };
  const seedSpans = new Map<string, { start: string; target: string }>();
  for (const seed of seeds) {
    seedSpans.set(seed.itemId, { start: seed.start, target: seed.target });
  }
  const moved = new Map(seedSpans);
  const queue: string[] = [...seedSpans.keys()];
  // The server rejects cyclic `blocks` graphs, but a runaway loop here would
  // hang the tab — bound the walk defensively and treat a trip as truncation.
  let guard = ROADMAP_CASCADE_MAX_ITEMS * 20;
  while (queue.length > 0) {
    if (guard-- <= 0) return truncated;
    const blockerId = queue.shift()!;
    const blockerTarget = moved.get(blockerId)?.target ?? rowById.get(blockerId)?.item.target_date;
    if (!blockerTarget) continue;
    for (const dependentId of dependents.get(blockerId) ?? []) {
      if (seedSpans.has(dependentId)) continue; // gesture-owned — never re-pushed
      const dependentRow = rowById.get(dependentId);
      if (!dependentRow || dependentRow.derived) continue; // derived spans track children
      const pending = moved.get(dependentId);
      const start = pending?.start ?? dependentRow.item.start_date;
      const target = pending?.target ?? dependentRow.item.target_date;
      if (!start || !target) continue;
      if (start > blockerTarget) continue; // slack — push-forward only
      const nextStart = shiftIso(blockerTarget, 1);
      const nextTarget = shiftIso(nextStart, isoDaysBetween(start, target));
      moved.set(dependentId, { start: nextStart, target: nextTarget });
      if (moved.size - seedSpans.size > ROADMAP_CASCADE_MAX_ITEMS) return truncated;
      queue.push(dependentId);
    }
  }

  const patches: RoadmapPlanPatch[] = [];
  const moves: RoadmapMove[] = [];
  for (const [itemId, span] of moved) {
    moves.push({ itemId, start: span.start, target: span.target });
    if (seedSpans.has(itemId)) continue;
    patches.push({ itemId, patch: { start_date: span.start, target_date: span.target } });
  }
  const cascadedCount = patches.length;
  patches.push(...epicStretchPatches(rows, moves));
  return { patches, cascadedCount, truncated: false };
}

/** Single-seed cascade (spec 78) — the plain move/resize commit path. */
export function cascadePlan(
  rows: RoadmapRow[],
  movedId: string,
  newSpan: { start: string; target: string },
): CascadePlan {
  return cascadePlanMulti(rows, [{ itemId: movedId, start: newSpan.start, target: newSpan.target }]);
}

/**
 * Epic container move (spec 81): a BODY drag of a scheduled, non-derived epic
 * shifts the epic AND every LOADED, SCHEDULED child by the same day delta —
 * durations preserved, the container's relative layout intact. Date-less
 * (tray) children are unaffected; a derived or date-less epic yields no plan
 * (its bar isn't directly draggable anyway). The epic's patch comes first.
 */
export function epicMovePlan(
  rows: RoadmapRow[],
  epicId: string,
  deltaDays: number,
): { patches: RoadmapPlanPatch[] } {
  const epicRow = rows.find((row) => row.item.id === epicId);
  if (!epicRow || epicRow.derived || !isScheduled(epicRow.item) || deltaDays === 0) {
    return { patches: [] };
  }
  const shifted = (item: Item): RoadmapPlanPatch => ({
    itemId: item.id,
    patch: {
      start_date: shiftIso(item.start_date!, deltaDays),
      target_date: shiftIso(item.target_date!, deltaDays),
    },
  });
  const patches: RoadmapPlanPatch[] = [shifted(epicRow.item)];
  for (const row of rows) {
    if (row.parentEpicId === epicId && isScheduled(row.item)) patches.push(shifted(row.item));
  }
  return { patches };
}

// ---------------------------------------------------------------------------
// Dependency health (spec 78)
// ---------------------------------------------------------------------------

/**
 * A `blocks` edge is VIOLATED when the dependent starts on/before its
 * blocker's end — the ordering the link promises is broken (dashed amber).
 */
export function isBlocksViolation(dependentStartIso: string, blockerTargetIso: string): boolean {
  return dependentStartIso <= blockerTargetIso;
}
