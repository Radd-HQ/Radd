import { QuickStar } from "../items/QuickStar";
import { Button } from "../Button";
import { TextField } from "../TextField";
import type { SectionSearchControl } from "../../lib/usePlanningSectionSearch";
import { accountStorageKey } from "../../lib/account-storage";
import { useEffect, useState, type ReactNode, type DragEvent as ReactDragEvent, type MouseEvent as ReactMouseEvent } from "react";
import { ChevronDown, ChevronRight, Search, X } from "lucide-react";
import type { BucketRef } from "../../lib/axis-dnd";
import { useBucketDrop } from "../../lib/bucket-drop";
import { usePeek } from "../../lib/hooks";
import {
  DEFAULT_LIST_SLOTS,
  defaultCardDisplay,
  type CardDisplayConfig,
} from "../../lib/card-display";
import { listSectionCollapseStorageKey } from "../../lib/constants";
import type { ColumnDef } from "../../lib/columns";
import type {
  Item,
  ItemRollup,
  ItemTimelogBatchEntry,
  RollupResponse,
  SlaBatchResponse,
  SlaBatchTimer,
  TimelogBatchResponse,
} from "../../lib/types";
import type { ViewGroup } from "../../lib/view-utils";
import { ColumnCell, ITEM_ZONE_CLASS, ListColumnHeader, SlackSpacer, itemZoneStyle } from "./ColumnCells";
import {
  CycleDatesBadge,
  CycleHeaderStats,
  CycleStatusPill,
  CycleHeaderProgress,
} from "../cycles/CycleBadges";
import {
  FlagBadge,
  VisibilityBadge,
  ItemKeyLink,
  KindBadge,
} from "../items/ItemBadges";

interface ViewListProps {
  /** One group = one section; a single unlabeled group renders flat. */
  groups: ViewGroup[];
  sectionSearch?: (group: ViewGroup) => SectionSearchControl;
  sectionTools?: (group: ViewGroup) => ReactNode;
  sectionStatus?: (group: ViewGroup) => ReactNode;
  /** Card display config (slots/labels/scale) — defaults to the list preset. */
  display?: CardDisplayConfig;
  /** Batch SLA timers by item id (spec 63) — set while the sla slot is on. */
  slaByItem?: SlaBatchResponse;
  /** Epic-progress rollups by item id (spec 76) — set while the progress slot
   *  is on and epic-kind items are on the page. */
  rollupByItem?: RollupResponse;
  /** Table columns (spec 108): rows render one typed cell per column (aligned
   * under the sticky header). FIT-TO-WIDTH: a trailing spacer absorbs the
   * slack and a handle borrows from its neighbour once that is spent, so the
   * row always spans exactly the screen. The column SET comes from the saved
   * view; widths are personal — the Item zone's included (RADD-1110). */
  listColumns: ColumnDef[];
  columnWidths?: Record<string, number>;
  onColumnsApply?: (patch: Record<string, number>) => void;
  onColumnsCommit?: (patch: Record<string, number>) => void;
  /** Logged-seconds batch for the logged_time column. */
  timelogByItem?: TimelogBatchResponse;
  /** id -> name for custom user-field cells. */
  usersById?: Map<string, string>;
  /** Persists collapsed sections per view (localStorage); omit for no persistence. */
  viewId?: string;
  /** Project scope for cycle-handle time stats — REQUIRED on project-scoped
   *  surfaces (cycles span projects; unscoped stats would show foreign time). */
  cycleStatsProjectId?: string;
  /** When set, rows are draggable and sections are drop targets (spec 24) —
   *  dropping onto another section sets the grouping axis's field on the item. */
  onMoveToBucket?: (item: Item, bucket: BucketRef) => void;
  /** Right-click quick-actions on a row (spec 24). */
  onContextMenu?: (item: Item, event: ReactMouseEvent) => void;
  /** When set, rows show a selection checkbox (multi-select + bulk, spec 24). */
  selectedIds?: Set<string>;
  onSelectToggle?: (item: Item, event: ReactMouseEvent) => void;
  /** Toggle the personal star (available to anyone who can read the item). */
  onStar?: (item: Item, star: boolean) => void;
  /** When set (view sorted by rank), dragging a row within its section reorders it. */
  onReorder?: (item: Item, afterId: string | null, beforeId: string | null) => void;
}

/** Bucket key for an ungrouped list (single flat section, header hidden). */
export const FLAT_GROUP_KEY = "__all__";

function readCollapsed(viewId: string | undefined): Set<string> {
  if (!viewId) return new Set();
  try {
    const raw = window.localStorage.getItem(accountStorageKey(listSectionCollapseStorageKey(viewId)));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(
      Array.isArray(parsed) ? parsed.filter((k): k is string => typeof k === "string") : [],
    );
  } catch {
    return new Set();
  }
}

/** True if the cursor is in the top half of the event's target row. */
function isTopHalf(event: ReactDragEvent): boolean {
  const rect = event.currentTarget.getBoundingClientRect();
  return event.clientY < rect.top + rect.height / 2;
}

/**
 * List rendering for a saved view (spec 09/23/24): collapsible grouped sections
 * of compact rows with a personal-star toggle. Cross-section drag sets the axis
 * field; within-section drag reorders (manual rank) when `onReorder` is set.
 */
export function ViewList({
  groups,
  sectionSearch,
  sectionTools,
  sectionStatus,
  display = defaultCardDisplay(DEFAULT_LIST_SLOTS),
  slaByItem,
  rollupByItem,
  listColumns,
  columnWidths,
  onColumnsApply,
  onColumnsCommit,
  timelogByItem,
  usersById,
  viewId,
  cycleStatsProjectId,
  onMoveToBucket,
  onContextMenu,
  selectedIds,
  onSelectToggle,
  onStar,
  onReorder,
}: ViewListProps) {
  const [searchOpen, setSearchOpen] = useState<Set<string>>(new Set());
  useEffect(() => setSearchOpen(new Set()), [viewId]);
  const flat = groups.length === 1 && groups[0].key === FLAT_GROUP_KEY;
  const [collapsed, setCollapsed] = useState<Set<string>>(() => readCollapsed(viewId));
  const collapseAccount = accountStorageKey("list-collapse");
  useEffect(() => setCollapsed(readCollapsed(viewId)), [viewId, collapseAccount]);
  // Within-section REORDER state (spec 24) — not covered by useBucketDrop:
  // the source section (fromKey) and the hovered row indicator (dropRow).
  const [fromKey, setFromKey] = useState<string | null>(null);
  const [dropRow, setDropRow] = useState<{ id: string; before: boolean } | null>(null);
  const selectable = Boolean(selectedIds && onSelectToggle);
  const reorderable = Boolean(onReorder);
  const draggable = Boolean(onMoveToBucket) || reorderable;
  // Cross-section bucket drop; the onClear extends its reset to the reorder state.
  const drop = useBucketDrop<Item>(draggable, () => {
    setFromKey(null);
    setDropRow(null);
  });
  const dragging = drop.dragging;
  const reset = drop.endDrag;

  const toggle = (key: string) => {
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      if (viewId) {
        try {
          window.localStorage.setItem(accountStorageKey(listSectionCollapseStorageKey(viewId)), JSON.stringify([...next]));
        } catch {
          // Best-effort — collapse still works for the session.
        }
      }
      return next;
    });
  };

  const reorderInto = (group: ViewGroup, target: Item, before: boolean) => {
    if (!dragging || group.reorderDisabled) return;
    const siblings = group.items.filter((i) => i.id !== dragging.id);
    const idx = siblings.findIndex((i) => i.id === target.id);
    const afterId = before ? (idx > 0 ? siblings[idx - 1].id : null) : target.id;
    const beforeId = before ? target.id : idx < siblings.length - 1 ? siblings[idx + 1].id : null;
    onReorder?.(dragging, afterId, beforeId);
    reset();
  };

  return (
    // Card layout: the scroll area IS the page ground, and each group is a card
    // floating on it. Full-bleed on purpose — the cards stretch to the window,
    // so a wide monitor buys longer rows rather than wider margins.
    // NOT a flex column: flex items shrink by default, so a view with many
    // groups (planning groups by epic — 92 of them here) squashed every card to
    // a ~12px strip. Block flow + space-y lets each card take its content height.
    <div className="flex-1 overflow-y-auto bg-base">
      {/* FIT-TO-WIDTH: the table always spans exactly the container — no
          horizontal scroll; the Item zone flexes and cells compress toward
          their minimums when space runs short. */}
      <div className="space-y-3 p-4">
      {/* Rendered even with no configured columns: the Item zone is a real
          column (RADD-1110), and its handle lives here. */}
      {(listColumns.length > 0 || (onColumnsApply && onColumnsCommit)) && (
        <ListColumnHeader
          columns={listColumns}
          widths={columnWidths ?? {}}
          onApply={onColumnsApply}
          onCommit={onColumnsCommit}
        />
      )}
      {groups.map((group) => {
        const search = sectionSearch?.(group);
        const searching = searchOpen.has(group.key) || Boolean(search?.filtered);
        const isCollapsed = !flat && collapsed.has(group.key);
        const Chevron = isCollapsed ? ChevronRight : ChevronDown;
        const isOver = drop.isOver(group.key);
        return (
          <section
            key={group.key}
            aria-label={group.label}
            className={
              "overflow-hidden rounded-xl border bg-surface shadow-lift " +
              // Drop target reads as a ring on the card rather than a wash —
              // a tint would fight the card's own surface.
              (isOver ? "border-accent ring-2 ring-accent/30" : "border-subtle")
            }
            // Section drop fires for drops NOT captured by a row (empty area,
            // header) → cross-section move. Row drops stopPropagation.
            {...drop.targetProps(group.key, (dragged) =>
              // The GROUP is the bucket ref — it carries the axis's structural
              // extras (an epic lane's `epicRef`) that {key,label} would drop.
              !group.dropDisabled && onMoveToBucket?.(dragged, group),
            )}
          >
            {!flat && (
              <header className={"border-b " + (isOver ? "border-accent/40 bg-accent/10" : "border-subtle")}>
                <div className="flex items-center">
                <button
                  type="button"
                  onClick={() => toggle(group.key)}
                  aria-expanded={!isCollapsed}
                  title={`${isCollapsed ? "Expand" : "Collapse"} ${group.label} (only for you)`}
                  className="flex min-w-0 flex-1 cursor-pointer flex-wrap items-center gap-2 px-4 py-2.5 text-left hover:bg-elevated/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
                >
                  <Chevron size={13} className="shrink-0 text-fg-muted" aria-hidden />
                  {group.dotClassName && (
                    <span className={`size-2 rounded-full ${group.dotClassName}`} aria-hidden />
                  )}
                  <h2 className="text-xs font-semibold text-fg">{group.label}</h2>
                  {!search?.filtered && <span className="text-xs text-fg-faint">{group.total !== undefined ? `${group.items.length} / ${group.total}` : group.items.length}</span>}
                  {group.cycleMeta ? (
                    <>
                      <CycleStatusPill status={group.cycleMeta.status} />
                      <CycleDatesBadge start={group.cycleMeta.start} end={group.cycleMeta.end} />
                      {/* Stats live on the right edge of the same line, mirroring
                          the rows' state-pill anchor; done-count sits outermost. */}
                      <span className="ml-auto flex flex-wrap items-center gap-1.5">
                        {group.cycleId && (
                          <CycleHeaderStats
                            showProgress
                            cycleId={group.cycleId}
                            projectId={cycleStatsProjectId}
                          />
                        )}

                      </span>
                    </>
                  ) : (
                    group.detail && (
                      <span className="truncate text-[11px] text-fg-muted">· {group.detail}</span>
                    )
                  )}
                </button>
                <div className="flex shrink-0 items-center gap-2 pr-3">
                  {sectionTools?.(group)}
                  {search && <Button size="sm" variant="ghost" aria-label={`Search ${group.label}`} title={`Search ${group.label}`} aria-expanded={searching}
                    onClick={() => {
                      setSearchOpen(previous => { const next = new Set(previous); if (searching) next.delete(group.key); else next.add(group.key); return next; });
                      if (searching) search.onChange("");
                      else if (isCollapsed) toggle(group.key);
                    }}><Search size={14} aria-hidden /></Button>}
                </div>
                </div>
                {search && searching && <div className="flex flex-wrap items-center gap-2 border-t border-subtle px-4 py-2">
                  <TextField label="Filter titles" autoFocus type="search" aria-label={`Search titles in ${group.label}`} placeholder="Filter issue titles…" value={search.value}
                    onChange={e => search.onChange(e.target.value)}
                    onKeyDown={e => { if (e.key === "Escape") { search.onChange(""); setSearchOpen(previous => { const next = new Set(previous); next.delete(group.key); return next; }); e.currentTarget.closest('section')?.querySelector<HTMLButtonElement>('button[aria-label^="Search "]')?.focus(); } }} />
                  {search.value && <Button size="sm" variant="ghost" aria-label={`Clear search in ${group.label}`} onClick={() => search.onChange("")}><X size={13} aria-hidden /></Button>}
                  {search.filtered && <span role="status" className="text-xs text-fg-muted">{search.pending ? "Searching…" : search.error ? "Search unavailable" : `${search.loaded} shown · ${search.total ?? "…"} matching`}</span>}
                  {search.error && <Button size="sm" variant="secondary" onClick={search.onRetry}>Retry search</Button>}
                </div>}
                {group.cycleId ? <CycleHeaderProgress cycleId={group.cycleId} projectId={cycleStatsProjectId} /> : group.progress !== undefined && (
                  <div className="h-0.5 w-full bg-elevated" aria-hidden>
                    <div className="h-full bg-accent" style={{ width: `${Math.round(group.progress * 100)}%` }} />
                  </div>
                )}
              </header>
            )}
            {sectionStatus?.(group)}
            {!isCollapsed && (
              <ul className={draggable && group.items.length === 0 ? "min-h-9" : undefined}>
                {group.items.length === 0 && group.emptyMessage && (
                  <li className="px-4 py-3 text-xs text-fg-muted">{group.emptyMessage}</li>
                )}
                {group.items.map((item) => {
                  const canReorderHere =
                    reorderable && !group.reorderDisabled && dragging !== null && fromKey === group.key && dragging.id !== item.id;
                  const indicator = dropRow?.id === item.id ? dropRow.before : null;
                  return (
                    <ListRow
                      key={item.id}
                      item={item}
                      sourceCycle={group.showSourceCycle ? item.cycle?.name : undefined}
                      draggable={draggable && !group.dragDisabled}
                      onDragStart={() => {
                        drop.startDrag(item);
                        setFromKey(group.key);
                      }}
                      onDragEnd={reset}
                      onContextMenu={onContextMenu}
                      selectable={selectable}
                      selected={selectedIds?.has(item.id) ?? false}
                      onSelectToggle={onSelectToggle}
                      onStar={onStar}
                      canReorderHere={canReorderHere}
                      dropIndicator={indicator}
                      onReorderOver={(before) => setDropRow({ id: item.id, before })}
                      onReorderDrop={(before) => reorderInto(group, item, before)}
                      display={display}
                      sla={slaByItem?.[item.id]}
                      rollup={rollupByItem?.[item.id]}
                      listColumns={listColumns}
                      columnWidths={columnWidths}
                      timelog={timelogByItem?.[item.id]}
                      usersById={usersById}
                    />
                  );
                })}
              </ul>
            )}
            {!isCollapsed && search?.filtered && search.more && <div className="p-3"><Button size="sm" variant="secondary" onClick={search.onMore}>Show more matches</Button></div>}
          </section>
        );
      })}
      </div>
    </div>
  );
}

interface ListRowProps {
  item: Item;
  sourceCycle?: string;
  display: CardDisplayConfig;
  /** Batch SLA timers for the sla slot (spec 63). */
  sla?: SlaBatchTimer[];
  /** Epic-progress aggregates for the progress slot (spec 76). */
  rollup?: ItemRollup;
  /** Table columns (spec 108). */
  listColumns: ColumnDef[];
  columnWidths?: Record<string, number>;
  timelog?: ItemTimelogBatchEntry;
  usersById?: Map<string, string>;
  draggable?: boolean;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  onContextMenu?: (item: Item, event: ReactMouseEvent) => void;
  selectable?: boolean;
  selected?: boolean;
  onSelectToggle?: (item: Item, event: ReactMouseEvent) => void;
  onStar?: (item: Item, star: boolean) => void;
  canReorderHere?: boolean;
  dropIndicator?: boolean | null; // true = insert-before (top), false = insert-after (bottom)
  onReorderOver?: (before: boolean) => void;
  onReorderDrop?: (before: boolean) => void;
}

function ListRow({
  item,
  sourceCycle,
  display,
  sla,
  rollup,
  listColumns,
  columnWidths,
  timelog,
  usersById,
  draggable,
  onDragStart,
  onDragEnd,
  onContextMenu,
  selectable,
  selected,
  onSelectToggle,
  onStar,
  canReorderHere,
  dropIndicator,
  onReorderOver,
  onReorderDrop,
}: ListRowProps) {
  const { open: openPeek } = usePeek();
  const open = () => openPeek(item.key);
  const indicatorClass =
    dropIndicator === true
      ? "shadow-[inset_0_2px_0_0] shadow-accent-hover"
      : dropIndicator === false
        ? "shadow-[inset_0_-2px_0_0] shadow-accent-hover"
        : "";
  return (
    <li
      draggable={draggable}
      onDragStart={
        draggable
          ? (event) => {
              event.dataTransfer.effectAllowed = "move";
              onDragStart?.();
            }
          : undefined
      }
      onDragEnd={draggable ? onDragEnd : undefined}
      // Within-section reorder: capture the drop so the section's cross-move doesn't also fire.
      onDragOver={
        canReorderHere
          ? (event) => {
              event.preventDefault();
              event.stopPropagation();
              onReorderOver?.(isTopHalf(event));
            }
          : undefined
      }
      onDrop={
        canReorderHere
          ? (event) => {
              event.preventDefault();
              event.stopPropagation();
              onReorderDrop?.(isTopHalf(event));
            }
          : undefined
      }
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
      tabIndex={0}
      className={
        "group/row flex items-center gap-2 border-b border-subtle/60 px-4 py-2 last:border-b-0 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus " +
        (selected ? "bg-accent/10 hover:bg-accent/15 " : "hover:bg-elevated/70 ") +
        (draggable ? "cursor-grab active:cursor-grabbing " : "cursor-pointer ") +
        indicatorClass
      }
    >
      {/* Table mode (spec 108), FIT-TO-WIDTH: the Item zone is a fixed-basis
          column (RADD-1110), cells share the row's single flex context
          (identical geometry to the header), and the trailing spacer absorbs
          the slack — the row can never outgrow the screen. */}
      <span style={itemZoneStyle(columnWidths ?? {})} className={ITEM_ZONE_CLASS}>
        <RowLeading
          item={item}
          selectable={selectable}
          selected={selected}
          onSelectToggle={onSelectToggle}
          onStar={onStar}
        />
        <span className="min-w-0 flex-1 text-[13px] text-heading"><span className="block truncate">{item.title}</span>{sourceCycle && <span className="block truncate text-[11px] text-fg-muted">From {sourceCycle}</span>}</span>
      </span>
      {listColumns.map((column) => (
        <ColumnCell
          key={column.id}
          column={column}
          item={item}
          width={columnWidths?.[column.id] ?? column.width}
          maxLabels={display.maxLabels}
          sla={sla}
          rollup={rollup}
          loggedSeconds={timelog?.logged_seconds}
          usersById={usersById}
        />
      ))}
      <SlackSpacer />
    </li>
  );
}

/** The uniform leading cells (selection, star, kind, flag, key) — identical
 * across a surface's rows, so table-mode alignment holds. */
function RowLeading({
  item,
  selectable,
  selected,
  onSelectToggle,
  onStar,
}: {
  item: Item;
  selectable?: boolean;
  selected?: boolean;
  onSelectToggle?: (item: Item, event: ReactMouseEvent) => void;
  onStar?: (item: Item, star: boolean) => void;
}) {
  return (
    <>
      {selectable && (
        <input
          type="checkbox"
          checked={selected}
          aria-label={`Select ${item.key}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelectToggle?.(item, event);
          }}
          onChange={() => {}}
          className={
            "size-3.5 shrink-0 accent-accent cursor-pointer " +
            (selected ? "" : "opacity-0 group-hover/row:opacity-100 focus:opacity-100")
          }
        />
      )}
      {onStar && (
        <QuickStar item={item} />
      )}
      <KindBadge kind={item.kind} size={13} />
      {item.flagged && <FlagBadge size={12} />}
      <VisibilityBadge visibility={item.visibility} size={12} />
      <ItemKeyLink itemKey={item.key} />
    </>
  );
}
