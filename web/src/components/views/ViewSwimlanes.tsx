import { useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useBucketDrop } from "../../lib/bucket-drop";
import type { CardLayout } from "../../lib/card-layout";
import { swimlaneCollapseStorageKey } from "../../lib/constants";
import type {
  FieldDef,
  Item,
  RollupResponse,
  SlaBatchResponse,
  TimelogBatchResponse,
} from "../../lib/types";
import type { BucketRef } from "../../lib/axis-dnd";
import type { ViewGroup } from "../../lib/view-utils";
import { BoardCard } from "../board/BoardCard";

interface ViewSwimlanesProps {
  /** Column buckets over ALL items — identical across every swimlane. */
  columns: ViewGroup[];
  /** Swimlane buckets over ALL items. */
  lanes: ViewGroup[];
  /** Persists collapsed lanes per view (localStorage). */
  viewId: string;
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
  /** When set, cards drag between cells and the drop sets BOTH the column and
   *  lane axis fields on the item (spec 24). */
  onMoveToCell?: (item: Item, column: BucketRef, lane: BucketRef) => void;
  /** RADD-1175: a column empty in EVERY lane renders as a rail (see ViewBoard). */
  collapseEmpty?: boolean;
  /** Right-click quick-actions on a card (spec 24). */
  onContextMenu?: (item: Item, event: ReactMouseEvent) => void;
  /** Multi-select (spec 68) — card checkboxes when provided. */
  selectedIds?: Set<string>;
  onSelectToggle?: (item: Item, event: ReactMouseEvent) => void;
}

const noDrag = () => {};

// Matches the board's column width so a view toggling swimlanes on/off keeps
// its horizontal rhythm.
const COLUMN_WIDTH_CLASSES = "w-80 shrink-0";
const RAIL_WIDTH_CLASSES = "w-10 shrink-0";

function readCollapsed(viewId: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(swimlaneCollapseStorageKey(viewId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((k): k is string => typeof k === "string") : []);
  } catch {
    return new Set();
  }
}

/**
 * Swimlane matrix for a saved board view (spec 11): rows = `swimlane_by`
 * buckets (sticky collapsible headers with counts, collapsed state persisted
 * per view), columns = `group_by` buckets (one sticky header row, consistent
 * across all lanes); each cell holds the items matching both bucket values —
 * empty cells render slim. When `onMoveToCell` is set (spec 24), cards drag
 * between cells and a drop writes BOTH the column and lane axis fields.
 */
export function ViewSwimlanes({
  columns,
  lanes,
  viewId,
  layout,
  usersById,
  cfByKey,
  slaByItem,
  rollupByItem,
  timelogByItem,
  onMoveToCell,
  onContextMenu,
  selectedIds,
  onSelectToggle,
  collapseEmpty,
}: ViewSwimlanesProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => readCollapsed(viewId));
  const dnd = Boolean(onMoveToCell);
  // Cells are keyed `${lane.key}::${column.key}` — one hovered cell at a time.
  const drop = useBucketDrop<Item>(dnd);

  const toggleLane = (laneKey: string) => {
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(laneKey)) next.delete(laneKey);
      else next.add(laneKey);
      try {
        window.localStorage.setItem(
          swimlaneCollapseStorageKey(viewId),
          JSON.stringify([...next]),
        );
      } catch {
        // Persistence is best-effort — collapse still works for the session.
      }
      return next;
    });
  };

  // RADD-1175: the rail the pointer is over; every rail expands mid-drag.
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const railOf = (column: ViewGroup) =>
    Boolean(collapseEmpty) && column.items.length === 0 && !drop.dragging && expandedKey !== column.key;
  const widthOf = (column: ViewGroup) => (railOf(column) ? RAIL_WIDTH_CLASSES : COLUMN_WIDTH_CLASSES);
  const hoverProps = (column: ViewGroup) =>
    collapseEmpty
      ? {
          onMouseEnter: () => setExpandedKey(column.key),
          onMouseLeave: () => setExpandedKey((k) => (k === column.key ? null : k)),
        }
      : {};
  // item id → column key, computed once; cells filter each lane by it.
  const columnOfItem = useMemo(() => {
    const map = new Map<string, string>();
    for (const column of columns) {
      for (const item of column.items) map.set(item.id, column.key);
    }
    return map;
  }, [columns]);

  return (
    <div className="flex-1 overflow-auto">
      <div className="min-w-max px-5 pb-6">
        {/* Column header row — sticky above every lane. */}
        <div className="sticky top-0 z-20 flex h-9 items-end gap-3 bg-base pb-1.5">
          {columns.map((column) => (
            <div
              key={column.key}
              data-board-column={column.key}
              data-collapsed={railOf(column) ? "true" : "false"}
              {...hoverProps(column)}
              className={`${widthOf(column)} flex items-center gap-2 px-1 transition-[width]`}
              title={railOf(column) ? `${column.label} — empty; hover to expand` : undefined}
            >
              {column.dotClassName && (
                <span className={`size-2 shrink-0 rounded-full ${column.dotClassName}`} aria-hidden />
              )}
              {!railOf(column) && (
                <>
                  <h2 className="truncate text-[13px] font-semibold text-fg">{column.label}</h2>
                  <span className="text-xs text-fg-muted">{column.items.length}</span>
                </>
              )}
            </div>
          ))}
        </div>

        {lanes.map((lane) => {
          const isCollapsed = collapsed.has(lane.key);
          const Chevron = isCollapsed ? ChevronRight : ChevronDown;
          return (
            <section key={lane.key} aria-label={`${lane.label} (${lane.items.length})`}>
              {/* Sticky lane header, pinned below the column row; the inner
                  button sticks left so the name survives horizontal scroll. */}
              <header className="sticky top-9 z-10 border-t border-subtle/70 bg-base py-1">
                <button
                  type="button"
                  onClick={() => toggleLane(lane.key)}
                  aria-expanded={!isCollapsed}
                  className="sticky left-5 flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 text-left hover:bg-elevated/60 focus-visible:outline-2 focus-visible:outline-focus"
                >
                  <Chevron size={13} className="text-fg-muted" aria-hidden />
                  {lane.dotClassName && (
                    <span className={`size-2 rounded-full ${lane.dotClassName}`} aria-hidden />
                  )}
                  <h3 className="text-[13px] font-semibold text-fg">{lane.label}</h3>
                  <span className="text-xs text-fg-muted">{lane.items.length}</span>
                </button>
              </header>

              {!isCollapsed && (
                <div className="flex gap-3 pb-3">
                  {columns.map((column) => {
                    const cellItems = lane.items.filter(
                      (item) => columnOfItem.get(item.id) === column.key,
                    );
                    const cellKey = `${lane.key}::${column.key}`;
                    const isOver = drop.isOver(cellKey);
                    return (
                      <div
                        key={column.key}
                        {...hoverProps(column)}
                        {...drop.targetProps(cellKey, (dragged) =>
                          onMoveToCell?.(
                            dragged,
                            // The GROUP is the bucket ref (it carries the axis's
                            // structural extras, e.g. an epic lane's `epicRef`);
                            // rebuilding {key,label} here dropped them.
                            column,
                            lane,
                          ),
                        )}
                        className={
                          // Each cell is a card on the page ground; BoardCards
                          // inside step up to `elevated` (same two-step language
                          // as the board columns).
                          `${widthOf(column)} flex flex-col gap-2 rounded-xl border p-2 shadow-lift transition-[width,background-color] ` +
                          (isOver
                            ? "border-accent bg-accent/5 ring-2 ring-accent/30 "
                            : "border-subtle bg-surface ") +
                          // Empty cells render slim instead of stretching to the row.
                          (cellItems.length === 0 ? "min-h-9 self-start" : "min-h-24")
                        }
                      >
                        {cellItems.map((item) => (
                          <BoardCard
                            key={item.id}
                            item={item}
                            layout={layout}
                            usersById={usersById}
                            cfByKey={cfByKey}
                            sla={slaByItem?.[item.id]}
                            rollup={rollupByItem?.[item.id]}
                            timelog={timelogByItem?.[item.id]}
                            onDragStart={dnd ? drop.startDrag : noDrag}
                            onDragEnd={dnd ? drop.endDrag : noDrag}
                            onContextMenu={onContextMenu}
                            selected={selectedIds?.has(item.id)}
                            onSelectToggle={onSelectToggle}
                          />
                        ))}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
