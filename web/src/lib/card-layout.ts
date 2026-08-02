import { DEFAULT_MAX_LABELS } from "./card-display";
import { CUSTOM_COLUMN_PREFIX } from "./columns";
import type { CardLayout, CardLayoutCell } from "./types/views";

export type { CardLayout, CardLayoutCell } from "./types/views";

/**
 * Board-card layout (spec 109): WHICH item attributes render on a board card
 * and WHERE. The shape is an 8-column grid — each placed attribute is a cell
 * with a row, a column, a span and an alignment — stored on the saved view
 * (`view.card_layout`, shared + edit-gated like `columns`); `null` means the
 * default card below. The renderer lays each occupied row out as a wrapping
 * flex LANE (cells sorted by col, the first `end`-aligned cell pushed right),
 * so span is a width HINT: exact for growable attributes (title, labels),
 * floor-of-natural-width for chips.
 *
 * Row 0 is the HEADER lane — its cells render inline with the fixed card
 * chrome (checkbox, kind/type, key, star, flag), which is never a cell. The
 * `title` cell is mandatory (server-enforced); everything else is optional.
 * Attribute ids share the list-column vocabulary (`lib/columns.ts` builtins +
 * `cf.<key>`), minus `type` (structural in the card header).
 */

export const CARD_GRID_COLS = 8;
export const CARD_LAYOUT_MAX_ROWS = 8;
export const CARD_LAYOUT_MAX_CELLS = 24;
/** Row 0 renders inline with the fixed header chrome, not as a body lane. */
export const CARD_HEADER_ROW = 0;
export const CARD_TITLE_ATTR = "title";

/** Builtin column ids that can never be placed on a card: `type` is part of
 * the fixed header chrome (TypeChip-else-KindBadge, exactly the old default). */
export const CARD_EXCLUDED_BUILTINS: ReadonlySet<string> = new Set(["type"]);

/** Attributes whose cell stretches to its span (everything else keeps its
 * chip's natural width and treats span as a minimum-basis hint). */
export const CARD_GROWABLE_ATTRS: ReadonlySet<string> = new Set([CARD_TITLE_ATTR, "labels"]);

/** One rendered row: cells sorted by col. Row numbers keep their stored value
 * (margins key off the ordinal position; empty rows collapse). */
export interface CardLane {
  row: number;
  cells: CardLayoutCell[];
}

/** The faithful translation of the pre-109 hardcoded board card — a view with
 * `card_layout: null` must render pixel-identically to the old anatomy. */
export const DEFAULT_BOARD_CARD_LAYOUT: CardLayout = {
  v: 1,
  cells: [
    { attr: "priority", row: 0, col: 7, span: 1, align: "end" },
    { attr: CARD_TITLE_ATTR, row: 1, col: 0, span: 8 },
    { attr: "labels", row: 2, col: 0, span: 8 },
    { attr: "parent", row: 3, col: 0, span: 1 },
    { attr: "progress", row: 3, col: 1, span: 1 },
    { attr: "cycle", row: 3, col: 2, span: 1 },
    { attr: "release", row: 3, col: 3, span: 1 },
    { attr: "team", row: 3, col: 4, span: 1 },
    { attr: "logged_time", row: 3, col: 6, span: 1, align: "end" },
    { attr: "assignee", row: 3, col: 7, span: 1, align: "end" },
  ],
  max_labels: DEFAULT_MAX_LABELS,
};

function sanitizeCell(candidate: unknown): CardLayoutCell | null {
  if (typeof candidate !== "object" || candidate === null) return null;
  const cell = candidate as Partial<CardLayoutCell>;
  if (typeof cell.attr !== "string" || cell.attr.length === 0) return null;
  if (typeof cell.row !== "number" || cell.row < 0 || cell.row >= CARD_LAYOUT_MAX_ROWS)
    return null;
  if (typeof cell.col !== "number" || cell.col < 0 || cell.col >= CARD_GRID_COLS) return null;
  const span =
    typeof cell.span === "number"
      ? Math.min(CARD_GRID_COLS - cell.col, Math.max(1, Math.round(cell.span)))
      : 1;
  return {
    attr: cell.attr,
    row: Math.round(cell.row),
    col: Math.round(cell.col),
    span,
    align: cell.align === "end" ? "end" : "start",
  };
}

/**
 * The layout a board surface should render: the view's stored layout when it
 * parses (malformed cells dropped — the server validates writes, but stored
 * JSON outlives validators), otherwise the default card. A layout that lost
 * its title cell is treated as malformed wholesale.
 */
export function activeCardLayout(
  view: { card_layout?: CardLayout | null } | null | undefined,
): CardLayout {
  const stored = view?.card_layout;
  if (!stored || !Array.isArray(stored.cells)) return DEFAULT_BOARD_CARD_LAYOUT;
  const cells = stored.cells
    .map(sanitizeCell)
    .filter((cell): cell is CardLayoutCell => cell !== null);
  if (!cells.some((cell) => cell.attr === CARD_TITLE_ATTR)) return DEFAULT_BOARD_CARD_LAYOUT;
  return {
    v: 1,
    cells,
    max_labels:
      typeof stored.max_labels === "number" && stored.max_labels >= 0
        ? stored.max_labels
        : DEFAULT_MAX_LABELS,
  };
}

/** Occupied rows in ascending order, cells sorted by col within each. */
export function lanesOf(layout: CardLayout): CardLane[] {
  const byRow = new Map<number, CardLayoutCell[]>();
  for (const cell of layout.cells) {
    const lane = byRow.get(cell.row);
    if (lane) lane.push(cell);
    else byRow.set(cell.row, [cell]);
  }
  return [...byRow.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([row, cells]) => ({ row, cells: cells.sort((a, b) => a.col - b.col) }));
}

/** Every placed attribute — drives the conditional batch fetches (sla /
 * progress / logged_time) and the cf-user directory fetch. */
export function placedAttrSet(layout: CardLayout): Set<string> {
  return new Set(layout.cells.map((cell) => cell.attr));
}

/** The `cf.<key>` keys placed on the card (registry keys, prefix stripped). */
export function placedCustomFieldKeys(layout: CardLayout): string[] {
  return layout.cells
    .filter((cell) => cell.attr.startsWith(CUSTOM_COLUMN_PREFIX))
    .map((cell) => cell.attr.slice(CUSTOM_COLUMN_PREFIX.length));
}

/** Deep equality against the default — Save PATCHes `null` for an untouched
 * layout so views keep tracking the (evolving) default card. */
export function isDefaultCardLayout(layout: CardLayout): boolean {
  const normalize = (l: CardLayout) =>
    JSON.stringify({
      cells: [...l.cells].sort((a, b) => a.row - b.row || a.col - b.col),
      max_labels: l.max_labels,
    });
  return normalize(layout) === normalize(DEFAULT_BOARD_CARD_LAYOUT);
}
