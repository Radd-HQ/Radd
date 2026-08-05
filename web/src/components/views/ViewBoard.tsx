import type { MouseEvent as ReactMouseEvent } from "react";
import { Plus } from "lucide-react";
import type { BucketRef } from "../../lib/axis-dnd";
import { useBucketDrop } from "../../lib/bucket-drop";
import type { CardLayout } from "../../lib/card-layout";
import type {
  FieldDef,
  Item,
  RollupResponse,
  SlaBatchResponse,
  TimelogBatchResponse,
} from "../../lib/types";
import type { ViewGroup } from "../../lib/view-utils";
import { BoardCard } from "../board/BoardCard";
import { formatPoints } from "../items/ItemBadges";
import { WipLimitMenu } from "./WipLimitMenu";
import { IconButton } from "../IconButton";

interface ViewBoardProps {
  groups: ViewGroup[];
  /** Card layout (spec 109) — passed through to every card. */
  layout?: CardLayout;
  /** Directory names + field defs for placed `cf.<key>` cells. */
  usersById?: Map<string, string>;
  cfByKey?: Map<string, FieldDef>;
  /** Batch SLA timers by item id (spec 63) — set while the sla slot is on. */
  slaByItem?: SlaBatchResponse;
  /** Epic-progress rollups by item id (spec 76) — set while the progress slot
   *  is on and epic-kind items are on the page. */
  rollupByItem?: RollupResponse;
  /** Logged/estimate seconds by item id — set while the logged-time slot is on. */
  timelogByItem?: TimelogBatchResponse;
  /** Quick add INTO a column (header + and the dashed bottom button): opens
   *  creation with the column's bucket prefilled. Omitted (no project context
   *  or no create permission) → no add affordances. */
  onQuickAdd?: (bucket: { key: string; label: string }) => void;
  /** Story points (spec 70): show each column's Σ of visible cards' points —
   *  the caller sets this only when the axis is state AND points are enabled. */
  showPoints?: boolean;
  /** SOFT WIP limits keyed by bucket key (spec 76): the header shows n/limit,
   *  amber at the limit, red above — the caller passes this only on
   *  state-axis boards (limits are keyed by state id). */
  wipLimits?: Record<string, number>;
  /** When set (state axis + the actor can edit the view), each column header
   *  gains a ⋯ menu with "Set WIP limit…" (null clears that column). */
  onSetWipLimit?: (bucketKey: string, limit: number | null) => void;
  /** When set, cards are draggable and columns are drop targets (spec 24) —
   *  dropping sets the grouping axis's field on the item. */
  onMoveToBucket?: (item: Item, bucket: BucketRef) => void;
  /** Right-click quick-actions on a card (spec 24). */
  onContextMenu?: (item: Item, event: ReactMouseEvent) => void;
  /** Multi-select (spec 68) — card checkboxes when provided. */
  selectedIds?: Set<string>;
  onSelectToggle?: (item: Item, event: ReactMouseEvent) => void;
}

const noop = () => {};

/** The column-header count: plain, or "n/limit" recolored by WIP pressure. */
function ColumnCount({ count, limit }: { count: number; limit: number | undefined }) {
  if (limit === undefined) {
    return <span className="text-xs text-fg-muted">{count}</span>;
  }
  const tone =
    count > limit ? "text-red-400" : count === limit ? "text-amber-400" : "text-fg-muted";
  return (
    <span className={`text-xs tabular-nums ${tone}`} title={`WIP limit ${limit}`}>
      {count}/{limit}
    </span>
  );
}

/**
 * Board rendering for a saved view: one column per group bucket (spec 09).
 * With `onMoveToBucket`, cards drag between columns and the drop sets the axis's
 * field (backlog → cycle, medium → high, …); otherwise the board is read-only.
 */
export function ViewBoard({
  groups,
  layout,
  usersById,
  cfByKey,
  slaByItem,
  rollupByItem,
  timelogByItem,
  onQuickAdd,
  showPoints,
  wipLimits,
  onSetWipLimit,
  onMoveToBucket,
  onContextMenu,
  selectedIds,
  onSelectToggle,
}: ViewBoardProps) {
  const dnd = Boolean(onMoveToBucket);
  const drop = useBucketDrop<Item>(dnd);
  const dragging = drop.dragging;

  // The whole board scrolls — both axes on this one container. Columns size to
  // their content (`items-start`), so a long column simply makes the page longer
  // rather than growing a scrollbar of its own.
  return (
    <div className="flex min-h-0 flex-1 items-start gap-5 overflow-auto bg-base px-5 py-4">
      {groups.map((group) => {
        const isOver = drop.isOver(group.key);
        const points = showPoints
          ? group.items.reduce((sum, item) => sum + (item.estimate_points ?? 0), 0)
          : 0;
        const limit = wipLimits?.[group.key];
        return (
          <section
            key={group.key}
            aria-label={`${group.label} (${group.items.length})`}
            className={
              // OPEN columns: cards float on the page ground (no boxed panel) —
              // the cards themselves are the only elevated surface, which is
              // what gives the board its calm. Height follows content (the row
              // is `items-start`); the body's min-h-24 keeps an empty column
              // droppable. The drop highlight paints the column's own rounded
              // region since there is no border to recolor.
              "group/column flex w-80 shrink-0 flex-col rounded-xl transition-colors " +
              (isOver ? "bg-accent/5 ring-2 ring-accent/30" : "")
            }
            {...drop.targetProps(group.key, (dragged) =>
              // The GROUP is the bucket ref — it carries the axis's structural
              // extras (an epic lane's `epicRef`) that {key,label} would drop.
              onMoveToBucket?.(dragged, group),
            )}
          >
            <header className="px-1.5 pb-1.5 pt-0.5">
              <div className="flex items-center gap-2">
                {group.dotClassName && (
                  <span className={`size-2 rounded-full ${group.dotClassName}`} aria-hidden />
                )}
                <h2 className="truncate text-[13px] font-semibold text-fg">{group.label}</h2>
                <ColumnCount count={group.items.length} limit={limit} />
                {showPoints && points > 0 && (
                  <span className="text-xs text-fg-muted" title="Story points in this column">
                    · Σ {formatPoints(points)} pts
                  </span>
                )}
                <span className="ml-auto flex items-center gap-0.5">
                  {onSetWipLimit && (
                    <WipLimitMenu
                      columnLabel={group.label}
                      limit={limit}
                      onSetLimit={(value) => onSetWipLimit(group.key, value)}
                    />
                  )}
                  {onQuickAdd && (
                    <IconButton
                      onClick={() => onQuickAdd({ key: group.key, label: group.label })}
                      aria-label={`Add issue to ${group.label}`}
                      title={`Add issue to ${group.label}`}
                    >
                      <Plus size={14} aria-hidden />
                    </IconButton>
                  )}
                </span>
              </div>
              {group.detail && (
                <p className="mt-0.5 truncate text-[11px] text-fg-muted">{group.detail}</p>
              )}
              {group.progress !== undefined && (
                <div className="mt-1.5 h-0.5 w-full rounded bg-elevated" aria-hidden>
                  <div
                    className="h-full rounded bg-accent"
                    style={{ width: `${Math.round(group.progress * 100)}%` }}
                  />
                </div>
              )}
            </header>
            <div
              className={
                // No scroll of its own: the body grows with its cards and the
                // page carries the scrolling. `min-h-24` keeps an empty column a
                // droppable target rather than a header-sized strip.
                "flex min-h-24 flex-col gap-2.5 px-0.5 pb-1 transition-colors " +
                (!isOver && dnd && dragging ? "rounded-xl bg-elevated/40" : "")
              }
            >
              {group.items.map((item) => (
                <BoardCard
                  key={item.id}
                  item={item}
                  layout={layout}
                  usersById={usersById}
                  cfByKey={cfByKey}
                  sla={slaByItem?.[item.id]}
                  rollup={rollupByItem?.[item.id]}
                  timelog={timelogByItem?.[item.id]}
                  onDragStart={dnd ? drop.startDrag : noop}
                  onDragEnd={dnd ? drop.endDrag : noop}
                  onContextMenu={onContextMenu}
                  selected={selectedIds?.has(item.id)}
                  onSelectToggle={onSelectToggle}
                />
              ))}
              {onQuickAdd && (
                <button
                  type="button"
                  onClick={() => onQuickAdd({ key: group.key, label: group.label })}
                  className="flex cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-strong px-2 py-2 text-xs text-fg-muted transition-colors hover:border-emphasis hover:text-fg focus-visible:outline-2 focus-visible:outline-focus"
                >
                  <Plus size={13} aria-hidden />
                  Add issue
                </button>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
