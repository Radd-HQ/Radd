import { useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from "react";
import {
  CARD_GRID_COLS,
  CARD_GROWABLE_ATTRS,
  CARD_HEADER_ROW,
  CARD_TITLE_ATTR,
  DEFAULT_BOARD_CARD_LAYOUT,
  lanesOf,
  type CardLayout,
  type CardLayoutCell,
} from "../../lib/card-layout";
import { useDurationConfig, usePeek } from "../../lib/hooks";
import type {
  FieldDef,
  Item,
  ItemRollup,
  ItemTimelogBatchEntry,
  SlaBatchTimer,
} from "../../lib/types";
import {
  FlagBadge,
  VisibilityBadge,
  ItemKeyLink,
  KindBadge,
  StarBadge,
  TypeChip,
} from "../items/ItemBadges";
import { renderCardCell, type CardCellCtx } from "./card-cells";
import { CardChildren } from "./CardChildren";

interface BoardCardProps {
  item: Item;
  onDragStart: (item: Item) => void;
  onDragEnd: () => void;
  /** Right-click quick-actions (spec 24); omitted → native menu. */
  onContextMenu?: (item: Item, event: ReactMouseEvent) => void;
  /** Card layout (spec 109) — defaults to the faithful pre-109 board card. */
  layout?: CardLayout;
  /** Batch SLA timers for a placed sla cell (spec 63); omitted renders nothing. */
  sla?: SlaBatchTimer[];
  /** Epic-progress aggregates for a placed progress cell (spec 76). */
  rollup?: ItemRollup;
  /** Logged/estimate seconds for a placed logged-time cell. */
  timelog?: ItemTimelogBatchEntry;
  /** Directory names + field defs for placed `cf.<key>` cells. */
  usersById?: Map<string, string>;
  cfByKey?: Map<string, FieldDef>;
  /** Multi-select (spec 68): checkbox on hover / while selected. */
  selected?: boolean;
  onSelectToggle?: (item: Item, event: ReactMouseEvent) => void;
}

/** A cell's flex sizing: growable attrs stretch to their span; chips keep
 * their natural width, with span > 1 acting as a minimum-basis hint.
 * Exported for the designer preview, which renders the same lanes. */
export function cellStyle(cell: CardLayoutCell): CSSProperties | undefined {
  const fraction = `${((cell.span / CARD_GRID_COLS) * 100).toFixed(2)}%`;
  if (CARD_GROWABLE_ATTRS.has(cell.attr)) {
    return { flexGrow: 1, flexBasis: cell.span === CARD_GRID_COLS ? "100%" : fraction, minWidth: 0 };
  }
  if (cell.span > 1) {
    return { flexBasis: fraction, minWidth: "min-content" };
  }
  return undefined;
}

/** One body lane: cells left-to-right, the first `end`-aligned RENDERED cell
 * pushed right (`ml-auto`) — the old footer's right cluster, generalized. */
function CardLane({
  cells,
  marginClass,
  ctx,
}: {
  cells: CardLayoutCell[];
  marginClass: string;
  ctx: CardCellCtx;
}) {
  const rendered = cells
    .map((cell) => ({ cell, node: renderCardCell(cell.attr, ctx) }))
    .filter((entry) => entry.node !== null);
  // Uniform card heights: a lane whose cells are all empty still RESERVES its
  // single-row height (min-h-5 = one chip row), so a card's height comes from
  // the designed LAYOUT, not from which fields happen to carry values.
  if (rendered.length === 0) return <div className={`${marginClass} min-h-5`} aria-hidden />;

  // A lane holding only the title renders the bare title paragraph, no flex
  // wrapper; min-h reserves both clamped lines so one-line titles don't
  // shrink the card (2 × leading-snug = 2.75em).
  if (rendered.length === 1 && rendered[0].cell.attr === CARD_TITLE_ATTR) {
    return (
      <p
        className={`${marginClass} min-h-[2.75em] line-clamp-2 text-sm font-medium leading-snug text-heading`}
      >
        {ctx.item.title}
      </p>
    );
  }

  const firstEnd = rendered.findIndex((entry) => entry.cell.align === "end");
  return (
    <div className={`${marginClass} flex min-h-5 flex-wrap items-center gap-1.5`}>
      {rendered.map((entry, index) => (
        <span
          key={entry.cell.attr}
          style={cellStyle(entry.cell)}
          className={
            "flex min-w-0 items-center" + (index === firstEnd ? " ml-auto" : "")
          }
        >
          {entry.node}
        </span>
      ))}
    </div>
  );
}

/** Top margins keyed by the lane's ordinal position among the STORED body
 * lanes (not the rendered ones): the old card's title/labels/footer rhythm
 * (1.5 / 2 / 2.5) survives even when a middle lane renders empty. */
export function laneMargin(index: number): string {
  if (index === 0) return "mt-1.5";
  if (index === 1) return "mt-2";
  return "mt-2.5";
}

/**
 * Draggable board card (board + swimlane surfaces). Fixed chrome — selection
 * checkbox, type/kind indicator, key, star, flag — frames a spec-109 card
 * layout: row 0 renders inline with the chrome (start cells after the key,
 * end cells after the flag), every other row is a wrapping flex lane. Click
 * opens the peek; the key is a real link.
 */
export function BoardCard({
  item,
  onDragStart,
  onDragEnd,
  onContextMenu,
  layout = DEFAULT_BOARD_CARD_LAYOUT,
  sla,
  rollup,
  timelog,
  usersById,
  cfByKey,
  selected,
  onSelectToggle,
}: BoardCardProps) {
  const { open: openPeek } = usePeek();
  const durations = useDurationConfig();
  const open = () => openPeek(item.key);
  // RADD-698: children expand IN the card. Collapsed is the default and is
  // byte-identical to the pre-698 card, so a board at rest is unchanged.
  const [childrenExpanded, setChildrenExpanded] = useState(false);

  const ctx: CardCellCtx = {
    item,
    sla,
    rollup,
    timelog,
    maxLabels: layout.max_labels,
    usersById,
    cfByKey,
    durations,
    childrenExpanded,
    onToggleChildren: () => setChildrenExpanded((value) => !value),
  };
  const lanes = lanesOf(layout);
  const headerLane = lanes.find((lane) => lane.row === CARD_HEADER_ROW);
  const bodyLanes = lanes.filter((lane) => lane.row !== CARD_HEADER_ROW);
  const headerCell = (cell: CardLayoutCell) => {
    const node = renderCardCell(cell.attr, ctx);
    return node === null ? null : (
      <span key={cell.attr} className="flex min-w-0 items-center">
        {node}
      </span>
    );
  };
  const headerStart = (headerLane?.cells ?? []).filter((cell) => cell.align !== "end");
  const headerEnd = (headerLane?.cells ?? []).filter((cell) => cell.align === "end");

  return (
    <div
      role="button"
      tabIndex={0}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        onDragStart(item);
      }}
      onDragEnd={onDragEnd}
      onContextMenu={
        onContextMenu
          ? (event) => {
              event.preventDefault();
              onContextMenu(item, event);
            }
          : undefined
      }
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === "Enter") open();
      }}
      className="group cursor-pointer rounded-xl border border-subtle bg-elevated p-3 shadow-lift transition-colors hover:border-emphasis focus-visible:outline-2 focus-visible:outline-focus active:cursor-grabbing"
    >
      <div className="flex items-center gap-1.5">
        {onSelectToggle && (
          <input
            type="checkbox"
            checked={selected ?? false}
            readOnly
            aria-label={`Select ${item.key}`}
            onClick={(event) => {
              event.stopPropagation();
              onSelectToggle(item, event);
            }}
            className={
              "size-3.5 shrink-0 cursor-pointer accent-accent " +
              (selected ? "" : "opacity-0 transition-opacity group-hover:opacity-100")
            }
          />
        )}
        {item.type ? <TypeChip type={item.type} /> : <KindBadge kind={item.kind} size={13} />}
        <ItemKeyLink itemKey={item.key} />
        {headerStart.map(headerCell)}
        <span className="ml-auto flex items-center gap-1.5">
          {item.starred && <StarBadge size={12} />}
          {item.flagged && <FlagBadge size={12} />}
          <VisibilityBadge visibility={item.visibility} size={12} />
          {headerEnd.map(headerCell)}
        </span>
      </div>

      {bodyLanes.map((lane, index) => (
        <CardLane key={lane.row} cells={lane.cells} marginClass={laneMargin(index)} ctx={ctx} />
      ))}

      {/* Below the laid-out lanes on purpose (RADD-698): the spec-109 designer
          owns the grid above, and an expansion is not a cell — so uniform card
          geometry survives, and collapsing restores the exact previous height. */}
      {childrenExpanded && <CardChildren parentId={item.id} />}
    </div>
  );
}
