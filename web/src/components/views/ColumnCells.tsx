import { COLUMN_MAX_WIDTH, type ColumnDef } from "../../lib/columns";
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

/**
 * The list table's column machinery (spec 108): one aligned header row with
 * drag-resize handles, and one typed cell per (column, item). Every cell is a
 * fixed-width box (overflow hidden) so values align down the page; empties
 * render a quiet dash so the grid reads as a grid.
 */

/** The Item zone's flex geometry — must stay identical in header and rows so
 * every row computes the same column positions. FIT-TO-WIDTH: the row always
 * spans exactly the container (no horizontal scroll); the Item zone absorbs
 * the slack and cells can compress toward their minimums when space is tight. */
export const ITEM_ZONE_CLASS = "flex min-w-[240px] flex-1 items-center gap-2 overflow-hidden";

/** A cell's flex style: preferred width as the basis, shrinkable to its min. */
export function cellStyle(column: ColumnDef, width: number): React.CSSProperties {
  return { flexBasis: width, minWidth: Math.min(column.minWidth, width) };
}

/**
 * A boundary handle BETWEEN two columns (fit-to-width resizing): dragging
 * TRANSFERS width across the boundary — the left side grows exactly what the
 * right side shrinks — so the handle tracks the cursor and the row never
 * outgrows the screen. `left === null` is the Item|first-column boundary (the
 * flexible Item zone absorbs the counterpart automatically). Double-click
 * (detected via pointerdown click count — preventDefault suppresses real
 * dblclick events) resets the pair to defaults.
 */
function BoundaryHandle({
  left,
  right,
  widths,
  onApply,
  onCommit,
}: {
  left: ColumnDef | null;
  right: ColumnDef;
  widths: Record<string, number>;
  onApply: (patch: Record<string, number>) => void;
  onCommit: (patch: Record<string, number>) => void;
}) {
  const leftWidth = left ? widths[left.id] ?? left.width : 0;
  const rightWidth = widths[right.id] ?? right.width;
  const patch = (dx: number): Record<string, number> => ({
    ...(left ? { [left.id]: leftWidth + dx } : {}),
    [right.id]: rightWidth - dx,
  });
  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize the ${left ? left.label : "Item"} column`}
      title="Drag to resize — double-click to reset"
      onPointerDown={(event) => {
        if (event.detail >= 2) {
          // Reset the pair to defaults.
          onCommit({
            ...(left ? { [left.id]: left.width } : {}),
            [right.id]: right.width,
          });
          return;
        }
        startHorizontalDrag(event, {
          start: 0,
          min: -Math.min(
            left ? leftWidth - left.minWidth : Number.POSITIVE_INFINITY,
            COLUMN_MAX_WIDTH - rightWidth,
          ),
          max: Math.min(
            left ? COLUMN_MAX_WIDTH - leftWidth : Number.POSITIVE_INFINITY,
            rightWidth - right.minWidth,
          ),
          onMove: (dx) => onApply(patch(dx)),
          onEnd: (dx) => onCommit(patch(dx)),
        });
      }}
      className="absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize rounded hover:bg-accent/40 active:bg-accent/60"
    />
  );
}

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
  const handles = Boolean(onApply && onCommit);
  return (
    <div className="sticky top-0 z-10 -mx-4 -mt-4 bg-base px-4 pb-1 pt-4">
      <div className="flex items-center gap-2 rounded-lg border border-subtle bg-surface px-4 py-1.5">
        <span
          className={
            ITEM_ZONE_CLASS +
            " relative text-[11px] font-medium uppercase tracking-wide text-fg-muted"
          }
        >
          <span className="truncate pr-1.5">Item</span>
          {handles && columns.length > 0 && (
            <BoundaryHandle
              left={null}
              right={columns[0]}
              widths={widths}
              onApply={onApply!}
              onCommit={onCommit!}
            />
          )}
        </span>
        {columns.map((column, index) => {
          const width = widths[column.id] ?? column.width;
          const next = columns[index + 1];
          return (
            <span
              key={column.id}
              style={cellStyle(column, width)}
              className="relative flex items-center overflow-hidden text-[11px] font-medium uppercase tracking-wide text-fg-muted"
            >
              <span className="truncate pr-1.5">{column.label}</span>
              {/* The LAST column's right edge is the screen edge — not a
                  boundary, so no handle. */}
              {handles && next && (
                <BoundaryHandle
                  left={column}
                  right={next}
                  widths={widths}
                  onApply={onApply!}
                  onCommit={onCommit!}
                />
              )}
            </span>
          );
        })}
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
      return item.type ? <TypeChip type={item.type} /> : <Dash />;
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
      return <PriorityIcon priority={item.priority} size={13} />;
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
