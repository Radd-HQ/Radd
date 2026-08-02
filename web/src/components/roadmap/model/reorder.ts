/** Roadmap vertical reorder + date ordering (spec 82): sibling-scoped rank helpers. */

import type { Item } from "../../../lib/types";
import { ROADMAP_ROW_H } from "./geometry";
import { RoadmapRowKind, type RoadmapRow } from "./rows";

// ---------------------------------------------------------------------------
// Vertical reorder + date ordering (spec 82): rows are rank-stable, so order
// becomes user-owned — these helpers resolve the sibling scope for the
// label drag-to-rank gesture and the "Order children by date" verb. Ranks
// are GLOBAL (spec 24, shared with lists); the roadmap only ever anchors a
// rank PATCH on SIBLINGS from its own row order.
// ---------------------------------------------------------------------------

/** A rank chain needs at least two members to change anything. */
export const RANK_CHAIN_MIN_ITEMS = 2;

/** Rows reorder among SIBLINGS only: top-level rows (epics + standalone
 *  leaves, interleaved) among themselves, children within the same epic. */
export function isRoadmapSibling(a: RoadmapRow, b: RoadmapRow): boolean {
  const aChild = a.rowKind === RoadmapRowKind.child;
  const bChild = b.rowKind === RoadmapRowKind.child;
  if (aChild !== bChild) return false;
  return !aChild || a.parentEpicId === b.parentEpicId;
}

/** The adjacent-sibling anchors for one rank PATCH (spec 24 semantics: null
 *  afterId = top of the sibling run, null beforeId = bottom). */
export interface RoadmapReorderNeighbours {
  afterId: string | null;
  beforeId: string | null;
}

/**
 * Resolve a label drop: `moved` lands on the top (`before` = true) or bottom
 * half of sibling `target` → the adjacent-sibling {afterId, beforeId} for the
 * rank PATCH, computed against the model's row order with `moved` excluded
 * (the ViewList idiom). Null when the pair aren't siblings — the drop is a
 * no-op, never a cross-scope move.
 */
export function roadmapReorderNeighbours(
  rows: RoadmapRow[],
  moved: RoadmapRow,
  target: RoadmapRow,
  before: boolean,
): RoadmapReorderNeighbours | null {
  if (moved.item.id === target.item.id || !isRoadmapSibling(moved, target)) return null;
  const siblings = rows.filter(
    (row) => row.item.id !== moved.item.id && isRoadmapSibling(moved, row),
  );
  const index = siblings.findIndex((row) => row.item.id === target.item.id);
  if (index === -1) return null;
  const afterId = before ? (index > 0 ? siblings[index - 1].item.id : null) : target.item.id;
  const beforeId = before
    ? target.item.id
    : index < siblings.length - 1
      ? siblings[index + 1].item.id
      : null;
  return { afterId, beforeId };
}

/** A bar-body reorder drag's hovered row half (spec 82 follow-up). */
export interface RowDropTarget {
  /** Index into the VISIBLE rows (fixed ROADMAP_ROW_H pitch). */
  index: number;
  /** True in the row's top half — insert BEFORE it (the ViewList idiom). */
  before: boolean;
}

/**
 * Map a body-local y (px below the FIRST row's top — measure the row
 * container itself; the axis header is a sibling, so no offset math) to the
 * visible row it falls in, plus which half. Rows are fixed ROADMAP_ROW_H
 * pitch. Null above the rows or past the last one.
 */
export function rowDropFromY(y: number, rowCount: number): RowDropTarget | null {
  if (y < 0 || rowCount <= 0) return null;
  const index = Math.floor(y / ROADMAP_ROW_H);
  if (index >= rowCount) return null;
  return { index, before: y - index * ROADMAP_ROW_H < ROADMAP_ROW_H / 2 };
}

/**
 * "Order children by date" (spec 82): start_date asc with date-less last,
 * then target_date asc (same null rule), then key (numeric-aware) — a
 * deterministic, stable order over an epic's loaded children. ISO days
 * compare lexicographically.
 */
export function childrenDateOrder(children: Item[]): Item[] {
  const nullsLast = (a: string | null | undefined, b: string | null | undefined): number => {
    if (a == null) return b == null ? 0 : 1;
    if (b == null) return -1;
    return a < b ? -1 : a > b ? 1 : 0;
  };
  return [...children].sort(
    (a, b) =>
      nullsLast(a.start_date, b.start_date) ||
      nullsLast(a.target_date, b.target_date) ||
      a.key.localeCompare(b.key, undefined, { numeric: true }),
  );
}
