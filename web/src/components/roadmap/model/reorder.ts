/** Roadmap vertical reorder + date ordering (spec 82). Ranks are GLOBAL
 *  (spec 24, shared with lists), so a roadmap rank PATCH only ever anchors
 *  on SIBLINGS from its own row order. */

import { ItemKind, type Item } from "../../../lib/types";
import { RoadmapRowKind, type RoadmapRow } from "./rows";

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
interface RoadmapReorderNeighbours {
  afterId: string | null;
  beforeId: string | null;
}

/** Resolve a label drop of `moved` on the top (`before`) or bottom half of
 *  sibling `target` into rank-PATCH anchors against the row order with
 *  `moved` excluded. Null when not siblings — never a cross-scope move. */
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
  return neighboursAround(siblings, target, before);
}

/** The anchors for landing on the top (`before`) / bottom half of `target`
 *  within its sibling run. Null when the target is not in the run. */
function neighboursAround(
  siblings: RoadmapRow[],
  target: RoadmapRow,
  before: boolean,
): RoadmapReorderNeighbours | null {
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

/** Where a tray drop lands (RADD-1522): the rank anchors for the save, and
 *  the row the insertion line should mark while the drag hovers. */
export interface TrayDropPlacement extends RoadmapReorderNeighbours {
  landing: { rowId: string; before: boolean };
}

/**
 * Resolve a tray drop on the top (`before`) / bottom half of `target` for an
 * item that is NOT a row yet. Its sibling scope comes from what it IS: an
 * epic, or a leaf whose parent is not a loaded epic, is a top-level row; a
 * child of a loaded epic is one of that epic's children. The target is then
 * projected onto that scope — a top-level item dropped on a child row goes
 * AFTER that epic's whole block (its last visible child is the landing); a
 * child dropped on its own epic's row goes to the top of the children.
 * Null when the target is outside the scope (a cross-scope rank would be a
 * cross-scope move) or the scope has nothing to anchor on — the model then
 * appends, as before.
 */
export function trayDropPlacement(
  rows: RoadmapRow[],
  item: Item,
  target: RoadmapRow,
  before: boolean,
): TrayDropPlacement | null {
  const parentId = item.parent?.id ?? null;
  const parentEpicId =
    item.kind !== ItemKind.epic &&
    parentId !== null &&
    rows.some((row) => row.rowKind === RoadmapRowKind.epic && row.item.id === parentId)
      ? parentId
      : null;
  if (parentEpicId !== null) {
    const siblings = rows.filter(
      (row) => row.rowKind === RoadmapRowKind.child && row.parentEpicId === parentEpicId,
    );
    if (target.rowKind === RoadmapRowKind.epic && target.item.id === parentEpicId) {
      if (siblings.length === 0) return null;
      return {
        afterId: null,
        beforeId: siblings[0].item.id,
        landing: { rowId: target.item.id, before: false },
      };
    }
    if (target.rowKind !== RoadmapRowKind.child || target.parentEpicId !== parentEpicId) {
      return null;
    }
    const neighbours = neighboursAround(siblings, target, before);
    return neighbours && { ...neighbours, landing: { rowId: target.item.id, before } };
  }
  const siblings = rows.filter((row) => row.rowKind !== RoadmapRowKind.child);
  if (target.rowKind === RoadmapRowKind.child) {
    const epicIndex = rows.findIndex((row) => row.item.id === target.parentEpicId);
    const epicRow = epicIndex >= 0 ? rows[epicIndex] : null;
    if (!epicRow) return null;
    // After the block: the last child that follows the epic in row order.
    let last = epicIndex;
    while (rows[last + 1]?.parentEpicId === epicRow.item.id) last++;
    const neighbours = neighboursAround(siblings, epicRow, false);
    return neighbours && { ...neighbours, landing: { rowId: rows[last].item.id, before: false } };
  }
  const neighbours = neighboursAround(siblings, target, before);
  return neighbours && { ...neighbours, landing: { rowId: target.item.id, before } };
}

/** A bar-body reorder drag's hovered row half (spec 82 follow-up). */
interface RowDropTarget {
  /** Index into the VISIBLE rows (one `rowH` pitch). */
  index: number;
  /** True in the row's top half — insert BEFORE it (the ViewList idiom). */
  before: boolean;
}

/**
 * Map a body-local y (px below the FIRST row's top — measure the row
 * container itself; the axis header is a sibling, so no offset math) to the
 * visible row it falls in, plus which half. Rows are one `rowH` pitch — the
 * LIVE pitch (RADD-1520), never the constant. Null above the rows or past the
 * last one.
 */
export function rowDropFromY(y: number, rowCount: number, rowH: number): RowDropTarget | null {
  if (y < 0 || rowCount <= 0 || rowH <= 0) return null;
  const index = Math.floor(y / rowH);
  if (index >= rowCount) return null;
  return { index, before: y - index * rowH < rowH / 2 };
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
