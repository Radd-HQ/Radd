import { useRef } from "react";
import {
  columnMaxWidth,
  columnWidth,
  TITLE_COLUMN,
  TITLE_COLUMN_ID,
  type ColumnDef,
} from "../../lib/columns";
import { startHorizontalDrag } from "../../lib/drag";
import { formatDuration } from "../../lib/duration";
import { useDurationConfig } from "../../lib/hooks";
import {
  ItemKind,
  type Item,
  type ItemRollup,
  type SlaBatchTimer,
} from "../../lib/types";
import { isOverdue } from "../items/CardSlots";
import { CustomCell, Dash, DateText } from "../items/CustomFieldValue";
import {
  AssigneeAvatar,
  CycleChip,
  DueBadge,
  LabelChips,
  ParentTag,
  PointsChip,
  PriorityIcon,
  ReleaseChip,
  StatePill,
  TeamBadge,
  TypeChip,
  UnassignedSlot,
} from "../items/ItemBadges";
import { RollupRowBar } from "../items/RollupBar";
import { SlaRowChip } from "../items/SlaChips";
import { PRIORITY_META } from "../../lib/meta";

/**
 * The list table's column machinery (spec 108): one aligned header row with
 * drag-resize handles, and one typed cell per (column, item). Every cell is a
 * fixed-width box (overflow hidden) so values align down the page; empties
 * render a quiet dash so the grid reads as a grid.
 */

/**
 * FIT-TO-WIDTH geometry, shared by the header and every row so they compute
 * the same column positions: the Item zone (selection/star/kind/flag/key/title)
 * is a fixed-basis column like the others (RADD-1110 — it used to be flex-1,
 * which is why it could not be resized), and a trailing SPACER absorbs the
 * slack so the row always spans exactly the container with no horizontal
 * scroll. When space is tight every cell compresses toward its minimum.
 */
export const ITEM_ZONE_CLASS = "flex items-center gap-2 overflow-hidden";
const SLACK_SPACER_CLASS = "min-w-0 flex-1";

/** A cell's flex style: preferred width as the basis, shrinkable to its min. */
export function cellStyle(column: ColumnDef, width: number): React.CSSProperties {
  return { flexBasis: width, minWidth: Math.min(column.minWidth, width) };
}

/** The Item zone's style for a row or the header, from the same widths map. */
export function itemZoneStyle(widths: Record<string, number>): React.CSSProperties {
  return cellStyle(TITLE_COLUMN, columnWidth(TITLE_COLUMN, widths));
}

/** The slack absorber every row and the header end with. */
export function SlackSpacer({ spacerRef }: { spacerRef?: React.Ref<HTMLSpanElement> }) {
  return <span ref={spacerRef} aria-hidden className={SLACK_SPACER_CLASS} />;
}

/**
 * A resize handle on a column's RIGHT edge. Dragging changes that column;
 * the trailing spacer gives or takes the difference, so the handle tracks the
 * cursor and the row never outgrows the screen. When the spacer has nothing
 * left to give (a tight layout — the default columns on a laptop), growth is
 * TRANSFERRED from the next column instead, down to its minimum: the handle
 * still moves, and the row still fits. Double-click (detected via pointerdown
 * click count — preventDefault suppresses real dblclick events) resets the
 * column to its default.
 */
function ColumnHandle({
  column,
  next,
  widths,
  slack,
  onApply,
  onCommit,
}: {
  column: ColumnDef;
  /** The column to the right, which lends width once the slack is spent. */
  next: ColumnDef | null;
  widths: Record<string, number>;
  /** The spacer's current width — measured at drag start, not on every move. */
  slack: () => number;
  onApply: (patch: Record<string, number>) => void;
  onCommit: (patch: Record<string, number>) => void;
}) {
  const width = columnWidth(column, widths);
  const nextWidth = next ? columnWidth(next, widths) : 0;
  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize the ${column.label} column`}
      title="Drag to resize — double-click to reset"
      data-resize-column={column.id}
      onPointerDown={(event) => {
        if (event.detail >= 2) {
          onCommit({ [column.id]: column.width });
          return;
        }
        const room = slack();
        const lendable = next ? nextWidth - next.minWidth : 0;
        const patch = (px: number): Record<string, number> => {
          const borrowed = Math.max(0, px - width - room);
          return next && borrowed > 0
            ? { [column.id]: px, [next.id]: nextWidth - borrowed }
            : { [column.id]: px };
        };
        startHorizontalDrag(event, {
          start: width,
          min: column.minWidth,
          max: Math.min(columnMaxWidth(column.id), width + room + lendable),
          onMove: (px) => onApply(patch(px)),
          onEnd: (px) => onCommit(patch(px)),
        });
      }}
      className="absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize rounded hover:bg-accent/40 active:bg-accent/60"
    />
  );
}

const HEADER_CELL_CLASS =
  "relative flex items-center overflow-hidden text-[11px] font-medium uppercase tracking-wide text-fg-muted";

/** The sticky header. Its wrapper paints an OPAQUE bg-base block spanning the
 * scroll container's full padded width, so rows scrolling past disappear
 * under it instead of peeking above the card (the "flying over" bug). */
export function ListColumnHeader({
  columns,
  widths,
  onApply,
  onCommit,
}: {
  columns: ColumnDef[];
  widths: Record<string, number>;
  onApply?: (patch: Record<string, number>) => void;
  onCommit?: (patch: Record<string, number>) => void;
}) {
  const spacer = useRef<HTMLSpanElement>(null);
  const slack = () => spacer.current?.getBoundingClientRect().width ?? 0;
  const handle = (column: ColumnDef, next: ColumnDef | null) =>
    onApply && onCommit ? (
      <ColumnHandle
        column={column}
        next={next}
        widths={widths}
        slack={slack}
        onApply={onApply}
        onCommit={onCommit}
      />
    ) : null;
  return (
    <div className="sticky top-0 z-10 -mx-4 -mt-4 bg-base px-4 pb-1 pt-4">
      <div className="flex items-center gap-2 rounded-lg border border-subtle bg-surface px-4 py-1.5">
        <span
          style={itemZoneStyle(widths)}
          data-column={TITLE_COLUMN_ID}
          className={ITEM_ZONE_CLASS + " " + HEADER_CELL_CLASS}
        >
          <span className="truncate pr-1.5">{TITLE_COLUMN.label}</span>
          {handle(TITLE_COLUMN, columns[0] ?? null)}
        </span>
        {columns.map((column, index) => (
          <span
            key={column.id}
            style={cellStyle(column, columnWidth(column, widths))}
            data-column={column.id}
            className={HEADER_CELL_CLASS}
          >
            <span className="truncate pr-1.5">{column.label}</span>
            {handle(column, columns[index + 1] ?? null)}
          </span>
        ))}
        <SlackSpacer spacerRef={spacer} />
      </div>
    </div>
  );
}

/** One fixed-width, typed cell. `usersById` resolves custom user-field ids
 * (fetched by the surface only while such a column is visible). */
export function ColumnCell({
  column,
  item,
  width,
  maxLabels,
  sla,
  rollup,
  loggedSeconds,
  usersById,
}: {
  column: ColumnDef;
  item: Item;
  width: number;
  maxLabels: number;
  sla?: SlaBatchTimer[];
  rollup?: ItemRollup;
  loggedSeconds?: number;
  usersById?: Map<string, string>;
}) {
  return (
    <span style={cellStyle(column, width)} className="flex items-center overflow-hidden">
      <CellContent
        column={column}
        item={item}
        maxLabels={maxLabels}
        sla={sla}
        rollup={rollup}
        loggedSeconds={loggedSeconds}
        usersById={usersById}
      />
    </span>
  );
}

function CellContent({
  column,
  item,
  maxLabels,
  sla,
  rollup,
  loggedSeconds,
  usersById,
}: {
  column: ColumnDef;
  item: Item;
  maxLabels: number;
  sla?: SlaBatchTimer[];
  rollup?: ItemRollup;
  loggedSeconds?: number;
  usersById?: Map<string, string>;
}) {
  const durations = useDurationConfig();
  if (column.cf) {
    return (
      <CustomCell
        type={column.cf.type}
        value={item.custom_fields?.[column.cf.key] ?? null}
        usersById={usersById}
        durations={durations}
      />
    );
  }
  switch (column.id) {
    case "type":
      // RADD-1292: the name beside the chip — a lone "T" said nothing.
      return item.type ? <TypeChip type={item.type} withLabel /> : <Dash />;
    case "parent":
      return item.parent ? <ParentTag parent={item.parent} /> : <Dash />;
    case "labels":
      return item.labels.length > 0 ? (
        <LabelChips labels={item.labels} max={maxLabels} nowrap />
      ) : (
        <Dash />
      );
    case "cycle":
      return item.cycle ? <CycleChip cycle={item.cycle} /> : <Dash />;
    case "release":
      return item.release ? <ReleaseChip release={item.release} /> : <Dash />;
    case "start_date":
      return item.start_date ? <DateText iso={item.start_date} /> : <Dash />;
    case "target_date":
      return item.target_date ? (
        <DueBadge date={item.target_date} overdue={isOverdue(item)} />
      ) : (
        <Dash />
      );
    case "team":
      return item.team ? <TeamBadge team={item.team} /> : <Dash />;
    case "priority":
      // RADD-1292: glyph AND word — the bars alone needed a legend.
      return (
        <span className="inline-flex min-w-0 items-center gap-1" data-priority={item.priority}>
          <PriorityIcon priority={item.priority} size={13} />
          <span className="truncate text-xs text-fg-secondary">{PRIORITY_META[item.priority].label}</span>
        </span>
      );
    case "assignee":
      return item.assignee ? <AssigneeAvatar assignee={item.assignee} /> : <UnassignedSlot />;
    case "reporter":
      return item.reporter ? (
        <span className="flex min-w-0 items-center gap-1.5">
          <AssigneeAvatar assignee={item.reporter} />
          <span className="truncate text-xs text-fg-secondary">{item.reporter.name}</span>
        </span>
      ) : (
        <Dash />
      );
    case "sla":
      return sla && sla.length > 0 ? <SlaRowChip timers={sla} /> : <Dash />;
    case "points":
      return item.estimate_points != null ? <PointsChip points={item.estimate_points} /> : <Dash />;
    case "progress":
      return item.kind === ItemKind.epic ? <RollupRowBar rollup={rollup} /> : <Dash />;
    case "logged_time":
      return loggedSeconds && loggedSeconds > 0 ? (
        <span className="text-xs tabular-nums text-fg-secondary">
          {formatDuration(loggedSeconds, durations)}
        </span>
      ) : (
        <Dash />
      );
    case "created":
      return <DateText iso={item.created_at} />;
    case "updated":
      return <DateText iso={item.updated_at} />;
    case "state":
      return <StatePill state={item.state} />;
    default:
      return <Dash />;
  }
}
