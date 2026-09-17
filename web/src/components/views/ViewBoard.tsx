import type { BoardLoading } from "../../lib/useBoardItems";
import { useBoardDragScroll } from "../../lib/board-scroll";
import { BoardLoadBoundary } from "./BoardLoadBoundary";
import { BoardNavigator } from "./BoardNavigator";
import { useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
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
  loading?: BoardLoading;
  updating?: boolean;
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
  /** RADD-1175: render an EMPTY column as a narrow rail. It stays a drop
   *  target — the rail expands on hover, and every rail expands for the
   *  duration of a drag, so an empty state is never unreachable. */
  collapseEmpty?: boolean;
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
  loading, updating,
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
  collapseEmpty,
}: ViewBoardProps) {
  const root = useRef<HTMLDivElement>(null);
  const dnd = Boolean(onMoveToBucket);
  const drop = useBucketDrop<Item>(dnd);
  const dragging = drop.dragging;
  const dragScroll = useBoardDragScroll(root, Boolean(dragging));
  // The one rail the pointer is over (or focus is in) — expanded in place.
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  return (
    <>
    <BoardNavigator columns={groups} updating={updating} onColumn={key=>{
      const node=Array.from(root.current?.querySelectorAll<HTMLElement>("[data-board-column]")??[]).find(n=>n.dataset.boardColumn===key);
      if(node&&root.current) root.current.scrollLeft=node.offsetLeft-root.current.offsetLeft-20;
    }} />
    <div ref={root} data-board-scroll onDragOverCapture={dragScroll} className="relative flex min-h-0 flex-1 items-stretch gap-5 overflow-x-auto overflow-y-hidden bg-base px-5 py-4">
      {groups.map((group) => {
        const isOver = drop.isOver(group.key);
        const points = showPoints
          ? group.totalPoints ?? group.items.reduce((sum, item) => sum + (item.estimate_points ?? 0), 0)
          : 0;
        const limit = wipLimits?.[group.key];
        const collapsed =
          Boolean(collapseEmpty) &&
          (group.total ?? group.items.length) === 0 &&
          !dragging &&
          expandedKey !== group.key;
        return (
          <section
            key={group.key}
            data-board-column={group.key}
            data-collapsed={collapsed ? "true" : "false"}
            aria-label={`${group.label} (${group.total ?? group.items.length})`}
            onMouseEnter={collapseEmpty ? () => setExpandedKey(group.key) : undefined}
            onMouseLeave={collapseEmpty ? () => setExpandedKey((k) => (k === group.key ? null : k)) : undefined}
            onFocus={collapseEmpty ? () => setExpandedKey(group.key) : undefined}
            onBlur={collapseEmpty ? () => setExpandedKey((k) => (k === group.key ? null : k)) : undefined}
            tabIndex={collapsed ? 0 : undefined}
            className={
              // OPEN columns: cards float on the page ground (no boxed panel) —
              // the cards themselves are the only elevated surface, which is
              // what gives the board its calm. Columns fill the viewport;
              // their bodies scroll independently. The drop highlight paints the rounded
              // region since there is no border to recolor.
              // RADD-1175: a collapsed rail is 40px of label; the width
              // transition is what makes hover-expand read as "the column
              // was always here", not as a layout jump.
              "group/column flex min-h-0 shrink-0 flex-col rounded-xl transition-[width,background-color] " +
              (collapsed ? "w-10 " : "w-80 ") +
              (isOver ? "bg-accent/5 ring-2 ring-accent/30" : "")
            }
            {...drop.targetProps(group.key, (dragged) =>
              // The GROUP is the bucket ref — it carries the axis's structural
              // extras (an epic lane's `epicRef`) that {key,label} would drop.
              onMoveToBucket?.(dragged, group),
            )}
          >
            {collapsed ? (
              <div
                className={
                  // Rotated label, reading bottom-to-top like a book spine; the
                  // min height keeps the rail a comfortable drop target.
                  "flex min-h-40 flex-col items-center gap-2 rounded-xl border border-dashed border-strong px-1 py-2 " +
                  "text-fg-muted hover:border-emphasis hover:text-fg"
                }
                title={`${group.label} — empty; hover to expand`}
              >
                {group.dotClassName && (
                  <span className={`size-2 shrink-0 rounded-full ${group.dotClassName}`} aria-hidden />
                )}
                <span className="[writing-mode:vertical-rl] rotate-180 truncate text-[12px] font-semibold">
                  {group.label}
                </span>
                {limit !== undefined && (
                  <span className="text-[10px] tabular-nums text-fg-faint" title={`WIP limit ${limit}`}>
                    0/{limit}
                  </span>
                )}
              </div>
            ) : (
            <>
            <header className="shrink-0 px-1.5 pb-1.5 pt-0.5">
              <div className="flex items-center gap-2">
                {group.dotClassName && (
                  <span className={`size-2 rounded-full ${group.dotClassName}`} aria-hidden />
                )}
                <h2 className="truncate text-[13px] font-semibold text-fg">{group.label}</h2>
                {group.total !== undefined && group.items.length < group.total && <span className="text-xs text-fg-muted">{group.items.length} loaded /</span>}
                <ColumnCount count={group.total ?? group.items.length} limit={limit} />
                {showPoints && points > 0 && (
                  <span className="text-xs text-fg-muted" title={group.totalPoints === undefined ? "Story points in loaded cards" : "Story points in all matching column issues"}>
                    · Σ {formatPoints(points)} pts{group.totalPoints === undefined && group.total !== undefined && group.items.length < group.total ? " loaded" : ""}
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
              data-column-scroll
              tabIndex={0}
              aria-label={`${group.label} issues`}
              className={
                // Header stays fixed; only this column scrolls. Children must
                // never shrink to fit the available viewport height.
                "flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto overscroll-contain px-0.5 pb-1 transition-colors [&>*]:shrink-0 " +
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
              <BoardLoadBoundary loading={group.total === 0 ? undefined : loading} column={group.key} />

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
            </>
            )}
          </section>
        );
      })}
    </div>
    </>
  );
}
