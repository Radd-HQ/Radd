import {
  CARD_GRID_COLS,
  CARD_GROWABLE_ATTRS,
  CARD_LAYOUT_MAX_CELLS,
  CARD_LAYOUT_MAX_ROWS,
  CARD_TITLE_ATTR,
  type CardLayout,
  type CardLayoutCell,
} from "../../../lib/card-layout";

/**
 * Pure draft operations for the card designer (spec 109). Every op returns a
 * NEW normalized layout, or `null` when the move can't be honored (row full,
 * grid overflow) — the caller simply ignores a null. Normalization keeps the
 * invariants the server checks: no duplicate attrs, no same-row overlap, rows
 * compressed into 0..n.
 */

/** A live drag: a palette chip being added, or a placed cell being moved. */
export interface DesignerDrag {
  kind: "add" | "move";
  attr: string;
}

/** Where a drop lands: a (row, col) slot, or a NEW row inserted after
 * `afterRow` (-1 = above everything, i.e. a new header lane). */
export type DropTarget = { row: number; col: number } | { newRowAfter: number };

/** Drop-zone key encoding shared by the preview's targetProps wiring. */
export function dropKey(target: DropTarget): string {
  return "newRowAfter" in target ? `new:${target.newRowAfter}` : `${target.row}:${target.col}`;
}

export function defaultSpanFor(attr: string): number {
  return CARD_GROWABLE_ATTRS.has(attr) ? CARD_GRID_COLS : 1;
}

/** Compress row numbers to 0..n (order kept), sort cells row-major. */
export function normalize(layout: CardLayout): CardLayout {
  const rows = [...new Set(layout.cells.map((cell) => cell.row))].sort((a, b) => a - b);
  const rowIndex = new Map(rows.map((row, index) => [row, index]));
  const cells = layout.cells
    .map((cell) => ({ ...cell, row: rowIndex.get(cell.row) ?? 0 }))
    .sort((a, b) => a.row - b.row || a.col - b.col);
  return { ...layout, cells };
}

/** Re-pack one row left-to-right after an insertion: overlapping cells are
 * pushed right; null when the row can't fit them all. */
function packRow(cells: CardLayoutCell[]): CardLayoutCell[] | null {
  const packed: CardLayoutCell[] = [];
  let cursor = 0;
  for (const cell of [...cells].sort((a, b) => a.col - b.col)) {
    const col = Math.max(cell.col, cursor);
    if (col + cell.span > CARD_GRID_COLS) return null;
    packed.push(cell.col === col ? cell : { ...cell, col });
    cursor = col + cell.span;
  }
  return packed;
}

function replaceRow(
  layout: CardLayout,
  row: number,
  rowCells: CardLayoutCell[] | null,
): CardLayout | null {
  if (rowCells === null) return null;
  return normalize({
    ...layout,
    cells: [...layout.cells.filter((cell) => cell.row !== row), ...rowCells],
  });
}

/**
 * Place `drag.attr` at `target`. Moves carry their cell's span/align along;
 * adds get the attr's default span (clamped to what the row can still take).
 * Overlapped neighbours shift right while they fit; otherwise null.
 */
export function placeCell(
  layout: CardLayout,
  drag: DesignerDrag,
  target: DropTarget,
): CardLayout | null {
  const existing = layout.cells.find((cell) => cell.attr === drag.attr);
  if (drag.kind === "add" && existing) return null; // one instance each
  if (layout.cells.length >= CARD_LAYOUT_MAX_CELLS && !existing) return null;
  const carried: Pick<CardLayoutCell, "span" | "align"> = {
    span: existing?.span ?? defaultSpanFor(drag.attr),
    align: existing?.align ?? "start",
  };
  const without: CardLayout = {
    ...layout,
    cells: layout.cells.filter((cell) => cell.attr !== drag.attr),
  };

  if ("newRowAfter" in target) {
    const occupied = new Set(without.cells.map((cell) => cell.row));
    if (occupied.size >= CARD_LAYOUT_MAX_ROWS) return null;
    // Shift every row below the insertion point down, then claim the gap.
    // Row numbers may exceed the cap transiently; normalize compresses them.
    const cells = without.cells.map((cell) =>
      cell.row > target.newRowAfter ? { ...cell, row: cell.row + 1 } : cell,
    );
    cells.push({ attr: drag.attr, row: target.newRowAfter + 1, col: 0, ...carried });
    return normalize({ ...without, cells });
  }

  const rowCells = without.cells.filter((cell) => cell.row === target.row);
  const span = Math.min(
    carried.span,
    Math.max(1, CARD_GRID_COLS - rowCells.reduce((sum, cell) => sum + cell.span, 0)),
  );
  const placed: CardLayoutCell = {
    attr: drag.attr,
    row: target.row,
    col: Math.min(target.col, CARD_GRID_COLS - span),
    span,
    align: carried.align,
  };
  return replaceRow(without, target.row, packRow([...rowCells, placed]));
}

/** The title cell is mandatory — removing it is refused. */
export function removeCell(layout: CardLayout, attr: string): CardLayout {
  if (attr === CARD_TITLE_ATTR) return layout;
  return normalize({ ...layout, cells: layout.cells.filter((cell) => cell.attr !== attr) });
}

/** Set a cell's span, clamped to the grid and its right-hand neighbour. */
export function resizeCell(layout: CardLayout, attr: string, span: number): CardLayout {
  const cell = layout.cells.find((entry) => entry.attr === attr);
  if (!cell) return layout;
  const neighbour = layout.cells
    .filter((entry) => entry.row === cell.row && entry.col > cell.col)
    .sort((a, b) => a.col - b.col)[0];
  const limit = (neighbour ? neighbour.col : CARD_GRID_COLS) - cell.col;
  const next = Math.min(Math.max(1, Math.round(span)), limit);
  if (next === cell.span) return layout;
  return normalize({
    ...layout,
    cells: layout.cells.map((entry) => (entry.attr === attr ? { ...entry, span: next } : entry)),
  });
}

export function toggleAlign(layout: CardLayout, attr: string): CardLayout {
  return normalize({
    ...layout,
    cells: layout.cells.map((cell) =>
      cell.attr === attr ? { ...cell, align: cell.align === "end" ? "start" : "end" } : cell,
    ),
  });
}

/** Keyboard ◀▶: swap with the adjacent cell in the row, or slide one column
 * into free space. Null when pinned against the edge. */
export function nudgeCol(layout: CardLayout, attr: string, delta: -1 | 1): CardLayout | null {
  const cell = layout.cells.find((entry) => entry.attr === attr);
  if (!cell) return null;
  const rowCells = layout.cells
    .filter((entry) => entry.row === cell.row)
    .sort((a, b) => a.col - b.col);
  const index = rowCells.findIndex((entry) => entry.attr === attr);
  const neighbour = rowCells[index + delta];
  if (neighbour) {
    // Swap the pair's order, then repack from the leftmost of the two.
    const swapped = rowCells.map((entry, i) =>
      i === index ? neighbour : i === index + delta ? cell : entry,
    );
    const start = Math.min(cell.col, neighbour.col);
    let cursor = start;
    const packed = swapped.map((entry) => {
      if (entry.col < start) return entry;
      const next = { ...entry, col: cursor };
      cursor += entry.span;
      return next;
    });
    if (packed.some((entry) => entry.col + entry.span > CARD_GRID_COLS)) return null;
    return replaceRow(layout, cell.row, packed);
  }
  const col = cell.col + delta;
  if (col < 0 || col + cell.span > CARD_GRID_COLS) return null;
  return replaceRow(
    layout,
    cell.row,
    rowCells.map((entry) => (entry.attr === attr ? { ...entry, col } : entry)),
  );
}

/** Keyboard ▲▼: move to the previous/next row (appended after its cells), or
 * into a fresh row when leaving the first/last one. */
export function nudgeRow(layout: CardLayout, attr: string, delta: -1 | 1): CardLayout | null {
  const cell = layout.cells.find((entry) => entry.attr === attr);
  if (!cell) return null;
  const rows = [...new Set(layout.cells.map((entry) => entry.row))].sort((a, b) => a - b);
  const index = rows.indexOf(cell.row);
  const targetRow = rows[index + delta];
  if (targetRow === undefined) {
    // Off the top/bottom: a new row of its own (unless it already is alone).
    if (layout.cells.filter((entry) => entry.row === cell.row).length === 1) return null;
    return placeCell(layout, { kind: "move", attr }, { newRowAfter: delta === -1 ? cell.row - 1 : cell.row });
  }
  const occupied = layout.cells
    .filter((entry) => entry.row === targetRow)
    .reduce((sum, entry) => sum + entry.span, 0);
  return placeCell(layout, { kind: "move", attr }, { row: targetRow, col: Math.min(occupied, CARD_GRID_COLS - 1) });
}
