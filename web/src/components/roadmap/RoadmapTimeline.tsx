import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import { Plus } from "lucide-react";
import {
  ROADMAP_BAND_THRESHOLD_PX,
  ROADMAP_HOVER_CARD_DELAY_MS,
} from "../../lib/constants";
import type { Item, RollupResponse, TimelogBatchResponse } from "../../lib/types";
import { BarRow } from "./BarRow";
import { Connectors, type ConnectorEdge, type RubberBand } from "./Connectors";
import { RoadmapHoverCard } from "./RoadmapHoverCard";
import {
  ROADMAP_ROW_H,
  RoadmapRowKind,
  barRenderRightX,
  clampDay,
  dayFromX,
  daysBetween,
  isRoadmapSibling,
  rowBarProgress,
  rowDropFromY,
  type RoadmapModel,
  type RoadmapRow,
  type RoadmapSpan,
} from "./roadmap-model";
import {
  BarDragMode,
  ExtendDirection,
  useBarDrag,
  type CommitModifiers,
  type ExtendDirectionValue,
} from "./useBarDrag";


/** Hover card anchoring: bottom-right of the CURSOR (offset both axes; the
 *  card flips above via anchor.top when the viewport bottom is near). */
const HOVER_CURSOR_OFFSET_PX = 14;

type HoverAnchor = { left: number; top: number; bottom: number };

export interface RoadmapTimelineProps {
  model: RoadmapModel;
  /** Rows with collapsed epics' children filtered out, in render order. */
  visibleRows: RoadmapRow[];
  dayWidth: number;
  /** LIVE label-gutter width (resizable, persisted per view). */
  labelWidth: number;
  /** Pointer-down on the labels/timeline divider — the owner runs the drag. */
  onLabelResizeStart: (event: ReactPointerEvent) => void;
  /** item.update on the project — false renders the read-only timeline. */
  canEdit: boolean;
  showConnectors: boolean;
  collapsedEpicIds: ReadonlySet<string>;
  /** Epic ids in the solo set (focus-scheduling mode). */
  soloIds: ReadonlySet<string>;
  /** Curated-membership state (roadmap wave); null onToggleMember = no curate rights. */
  memberIds: ReadonlySet<string>;
  onToggleMember: ((itemId: string, makeMember: boolean) => void) | null;
  /** Selection (viewport wave): label clicks + the rubber band feed it. */
  selectedIds: ReadonlySet<string>;
  onSelectRow: (itemId: string, additive: boolean) => void;
  onRubberSelect: (ids: string[], additive: boolean) => void;
  /** The horizontal scroll pane — drag auto-scroll + edge extension (spec 78). */
  scrollRef: RefObject<HTMLDivElement | null>;
  /** Grow the domain a month that direction (the +caps and drag auto-extend). */
  onExtend: (direction: ExtendDirectionValue) => void;
  onToggleCollapse: (epicId: string) => void;
  onToggleSolo: (epicId: string) => void;
  onCommitSpan: (row: RoadmapRow, span: RoadmapSpan, modifiers: CommitModifiers) => void;
  /** canEdit AND the view is rank-ordered (spec 82) — row labels become
   *  HTML5 drag-to-reorder handles among SIBLINGS. */
  canReorder: boolean;
  /** A drop on the top (`before` = true) / bottom half of a sibling — persist
   *  the rank move (spec 82). Both reorder routes land here: the label's
   *  HTML5 drag AND the vertical bar-body pointer drag (follow-up). */
  onReorderRow: (moved: RoadmapRow, target: RoadmapRow, before: boolean) => void;
  /** ○-handle drop at (x, y) client coords — opens the type popover (spec 78). */
  onCreateLink: (row: RoadmapRow, targetItemId: string, x: number, y: number) => void;
  /** Connector click — opens the link popover (gated on canEdit here). */
  onEdgeClick: (edge: ConnectorEdge, x: number, y: number) => void;
  onContextMenu: (row: RoadmapRow, x: number, y: number) => void;
  /** The tray item mid-HTML5-drag, if any — lanes accept it as a drop. */
  trayDragItem: Item | null;
  onTrayDrop: (item: Item, dayIndex: number) => void;
  /** Raw estimate/logged seconds per leaf item id (progress tints + hover
   *  card) — undefined while pending/failed/disabled, degrading to no tint. */
  timelogByItem: TimelogBatchResponse | undefined;
  /** done/total rollups per epic row id (epic tints + hover card) — same
   *  quiet degradation. */
  rollupByItem: RollupResponse | undefined;
}

/** Axis (months + weeks) + a positioned, gesture-wired bar per row; row
 *  labels double as sibling drag-to-reorder handles (spec 82), and a
 *  VERTICAL bar-body drag reorders the same way (spec 82 follow-up). */
export function RoadmapTimeline({
  model,
  visibleRows,
  dayWidth,
  labelWidth,
  onLabelResizeStart,
  canEdit,
  showConnectors,
  collapsedEpicIds,
  soloIds,
  memberIds,
  onToggleMember,
  selectedIds,
  onSelectRow,
  onRubberSelect,
  scrollRef,
  onExtend,
  onToggleCollapse,
  onToggleSolo,
  onCommitSpan,
  canReorder,
  onReorderRow,
  onCreateLink,
  onEdgeClick,
  onContextMenu,
  trayDragItem,
  onTrayDrop,
  timelogByItem,
  rollupByItem,
}: RoadmapTimelineProps) {
  const innerWidth = model.domainDays * dayWidth;
  const bodyRef = useRef<HTMLDivElement>(null);
  const [trayDropDay, setTrayDropDay] = useState<number | null>(null);

  // Row reorder (spec 82): the label-dragged row + the hovered sibling's drop
  // indicator. HTML5 drag like ViewList rows — separate from the pointer-event
  // bar gestures (useBarDrag) and from the tray's HTML5 drag (trayDragItem).
  const [rowDrag, setRowDrag] = useState<RoadmapRow | null>(null);
  const [rowDrop, setRowDrop] = useState<{ id: string; before: boolean } | null>(null);
  const endRowDrag = useCallback(() => {
    setRowDrag(null);
    setRowDrop(null);
  }, []);

  // Bar-body vertical reorder (spec 82 follow-up): a reorder-mode pointer
  // drag maps its body-local y to the visible row under it — rows are fixed
  // ROADMAP_ROW_H pitch and bodyRef starts at the FIRST row (the axis header
  // is a sibling), so `rowDropFromY` needs no offset math. ONE resolver feeds
  // both the live indicator and the drop, so they can never disagree. Only
  // SIBLING rows resolve (isRoadmapSibling, self excluded): anything else is
  // null → no indicator, drop is a no-op.
  const resolveReorderDrop = useCallback(
    (moved: RoadmapRow, y: number): { target: RoadmapRow; before: boolean } | null => {
      const hit = rowDropFromY(y, visibleRows.length);
      if (!hit) return null;
      const target = visibleRows[hit.index];
      if (target.item.id === moved.item.id || !isRoadmapSibling(moved, target)) return null;
      return { target, before: hit.before };
    },
    [visibleRows],
  );
  const handleReorderDrop = useCallback(
    (moved: RoadmapRow, y: number) => {
      const hit = resolveReorderDrop(moved, y);
      if (hit) onReorderRow(moved, hit.target, hit.before);
    },
    [resolveReorderDrop, onReorderRow],
  );

  const drag = useBarDrag({
    labelWidth,
    enabled: canEdit,
    dayWidth,
    domainDays: model.domainDays,
    bodyRef,
    scrollRef,
    onCommitSpan,
    onCreateLink,
    onAutoExtend: onExtend,
    reorderEnabled: canReorder,
    onReorderDrop: handleReorderDrop,
  });

  // Live reorder-drag presentation: the dragged row dims, and the hovered
  // sibling half shows the SAME inset drop indicator the label drag draws
  // (rowDrop and a pointer reorder can never be live at once — one is an
  // HTML5 drag, the other holds pointer capture).
  const reorderState =
    drag.state?.started && drag.state.mode === BarDragMode.reorder ? drag.state : null;
  const barReorderHit =
    reorderState?.pointer != null
      ? resolveReorderDrop(reorderState.row, reorderState.pointer.y)
      : null;
  const dropIndicator =
    rowDrop ??
    (barReorderHit ? { id: barReorderHit.target.item.id, before: barReorderHit.before } : null);

  // Hover card (bar-presentation polish): a ~350ms dwell on a bar opens the
  // floating info card; ANY live gesture state (move/resize/link rubber band
  // — even the pre-threshold pointerdown) suppresses it, as do leave, scroll,
  // and click/context-menu. The anchor rect is captured at fire time so the
  // card lands where the bar actually is.
  // The card anchors to the CURSOR (bottom-right), not the bar rect — a long
  // bar would otherwise drop the card far from where the user is pointing.
  const [hover, setHover] = useState<{ row: RoadmapRow; anchor: HoverAnchor } | null>(null);
  const hoverTimerRef = useRef<number | null>(null);
  const pointerRef = useRef({ x: 0, y: 0 });
  const dragStateRef = useRef(drag.state);
  dragStateRef.current = drag.state;
  const dragActive = drag.state !== null;

  const clearHover = useCallback(() => {
    if (hoverTimerRef.current !== null) {
      window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    setHover((current) => (current === null ? current : null));
  }, []);

  const cursorAnchor = useCallback(
    (): HoverAnchor => ({
      left: pointerRef.current.x + HOVER_CURSOR_OFFSET_PX,
      top: pointerRef.current.y - HOVER_CURSOR_OFFSET_PX,
      bottom: pointerRef.current.y + HOVER_CURSOR_OFFSET_PX,
    }),
    [],
  );

  const scheduleHover = useCallback(
    (row: RoadmapRow, event: ReactPointerEvent) => {
      pointerRef.current = { x: event.clientX, y: event.clientY };
      if (dragStateRef.current) return;
      if (hoverTimerRef.current !== null) window.clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = window.setTimeout(() => {
        hoverTimerRef.current = null;
        // Re-check at fire time — a drag may have begun during the dwell.
        if (dragStateRef.current) return;
        setHover({ row, anchor: cursorAnchor() });
      }, ROADMAP_HOVER_CARD_DELAY_MS);
    },
    [cursorAnchor],
  );

  // While the card is up, it follows the cursor along the bar.
  const moveHover = useCallback(
    (row: RoadmapRow, event: ReactPointerEvent) => {
      pointerRef.current = { x: event.clientX, y: event.clientY };
      setHover((current) =>
        current !== null && current.row.item.id === row.item.id
          ? { row: current.row, anchor: cursorAnchor() }
          : current,
      );
    },
    [cursorAnchor],
  );

  useEffect(() => {
    if (dragActive) clearHover();
  }, [dragActive, clearHover]);

  // Scrolling slides the bar out from under a stationary pointer — drop the
  // card rather than letting it float detached.
  useEffect(() => {
    const pane = scrollRef.current;
    if (!pane) return;
    pane.addEventListener("scroll", clearHover, { passive: true });
    return () => pane.removeEventListener("scroll", clearHover);
  }, [scrollRef, clearHover]);

  useEffect(() => clearHover, [clearHover]);

  // A before-extension moves the domain start earlier mid-drag — shift the
  // live drag's indices so its ghost stays on the same calendar dates
  // (useLayoutEffect: corrected before the frame paints).
  const prevDomainStartRef = useRef<Date | null>(model.domainStart);
  useLayoutEffect(() => {
    const previous = prevDomainStartRef.current;
    prevDomainStartRef.current = model.domainStart;
    if (previous && model.domainStart) {
      const shift = daysBetween(model.domainStart, previous);
      if (shift !== 0) drag.shiftDomain(shift);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model.domainStart]);

  const visibleIds = useMemo(
    () => new Set(visibleRows.map((row) => row.item.id)),
    [visibleRows],
  );
  const rowIndexById = useMemo(
    () => new Map(visibleRows.map((row, index) => [row.item.id, index] as const)),
    [visibleRows],
  );

  // Compact zoom halves the week-label density so ticks don't collide.
  const weekTicks = dayWidth < 8 ? model.weeks.filter((week) => week.index % 14 === 0) : model.weeks;

  // Epic container drag (spec 81): while an epic's BODY moves (and Alt isn't
  // held), its child bars render translated by the epic ghost's live snapped
  // delta — the container visibly slides as one. The delta is read off the
  // epic's preview span so a domain clamp applies to the children too.
  const epicDrag =
    drag.state?.started &&
    drag.state.mode === BarDragMode.move &&
    drag.state.row.rowKind === RoadmapRowKind.epic &&
    !drag.state.alt
      ? {
          epicId: drag.state.row.item.id,
          delta:
            (drag.previewSpan(drag.state.row)?.startIndex ?? drag.state.row.startIndex) -
            drag.state.row.startIndex,
        }
      : null;

  // Child-container regions (bar-presentation polish): one translucent box
  // behind each EXPANDED epic and its scheduled child rows — horizontal span
  // is the union of the epic and its children, vertical span runs from the
  // epic row's top to the last child row's bottom. Child rows sit directly
  // after their epic in visibleRows, so a forward scan finds each block.
  const containerRegions = useMemo(() => {
    const regions: {
      epicId: string;
      rowIndex: number;
      rowCount: number;
      startIndex: number;
      /** Region right edge in px — the max CLAMPED bar edge among members,
       *  so a min-width bar never pokes past its container box. */
      rightX: number;
    }[] = [];
    visibleRows.forEach((row, index) => {
      if (row.rowKind !== RoadmapRowKind.epic) return;
      let startIndex = row.startIndex;
      let rightX = barRenderRightX(row.startIndex, row.endIndex, dayWidth);
      let childCount = 0;
      for (
        let next = index + 1;
        next < visibleRows.length && visibleRows[next].parentEpicId === row.item.id;
        next++
      ) {
        const child = visibleRows[next];
        childCount++;
        startIndex = Math.min(startIndex, child.startIndex);
        rightX = Math.max(rightX, barRenderRightX(child.startIndex, child.endIndex, dayWidth));
      }
      if (childCount === 0) return;
      regions.push({
        epicId: row.item.id,
        rowIndex: index,
        rowCount: childCount + 1,
        startIndex,
        rightX,
      });
    });
    return regions;
  }, [visibleRows, dayWidth]);

  const linkState = drag.state?.mode === BarDragMode.link && drag.state.started ? drag.state : null;
  const rubber: RubberBand | null =
    linkState?.pointer != null
      ? {
          x1: barRenderRightX(linkState.row.startIndex, linkState.row.endIndex, dayWidth),
          y1: (rowIndexById.get(linkState.row.item.id) ?? 0) * ROADMAP_ROW_H + ROADMAP_ROW_H / 2,
          x2: linkState.pointer.x,
          y2: linkState.pointer.y,
        }
      : null;

  // Rubber-band selection (viewport wave): a left-drag starting on EMPTY body
  // space (never a bar/label/handle — those own their gestures) draws a band;
  // release selects every visible row whose bar intersects it. Short drags
  // are plain clicks and clear the selection. Shift adds to it.
  const [band, setBand] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(
    null,
  );
  const bandStart = (event: ReactMouseEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("button, a, [draggable='true'], [role='separator'], input")) return;
    const rect = bodyRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x0 = event.clientX - rect.left;
    const y0 = event.clientY - rect.top;
    const additive = event.shiftKey;
    let active = false;
    const move = (e: MouseEvent) => {
      const r = bodyRef.current?.getBoundingClientRect();
      if (!r) return;
      const x1 = e.clientX - r.left;
      const y1 = e.clientY - r.top;
      if (!active && Math.hypot(x1 - x0, y1 - y0) < ROADMAP_BAND_THRESHOLD_PX) return;
      active = true;
      setBand({ x0, y0, x1, y1 });
    };
    const up = (e: MouseEvent) => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      setBand(null);
      if (!active) {
        if (!additive) onRubberSelect([], false); // background click clears
        return;
      }
      const r = bodyRef.current?.getBoundingClientRect();
      if (!r) return;
      const x1 = e.clientX - r.left;
      const y1 = e.clientY - r.top;
      const dayLo = Math.floor((Math.min(x0, x1) - labelWidth) / dayWidth);
      const dayHi = Math.ceil((Math.max(x0, x1) - labelWidth) / dayWidth);
      const rowLo = Math.max(0, Math.floor(Math.min(y0, y1) / ROADMAP_ROW_H));
      const rowHi = Math.min(
        visibleRows.length - 1,
        Math.floor(Math.max(y0, y1) / ROADMAP_ROW_H),
      );
      const ids: string[] = [];
      for (let i = rowLo; i <= rowHi; i++) {
        const row = visibleRows[i];
        if (row && row.startIndex <= dayHi && row.endIndex >= dayLo) ids.push(row.item.id);
      }
      onRubberSelect(ids, additive);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };

  // Tray drag-in: the whole body is the lane; drops on the gutter ignored —
  // including the STICKY gutter, which overlays real day columns once the
  // pane is scrolled (layout x alone can't tell those apart).
  const dayAtEvent = (event: ReactDragEvent<HTMLElement>): number | null => {
    const rect = bodyRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const pane = scrollRef.current?.getBoundingClientRect();
    if (pane && event.clientX - pane.left < labelWidth) return null;
    const x = event.clientX - rect.left - labelWidth;
    if (x < 0) return null;
    return clampDay(dayFromX(x, dayWidth), model.domainDays);
  };
  const trayTargetProps =
    canEdit && trayDragItem
      ? {
          onDragOver: (event: ReactDragEvent<HTMLElement>) => {
            const day = dayAtEvent(event);
            if (day === null) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            setTrayDropDay(day);
          },
          onDragLeave: (event: ReactDragEvent<HTMLElement>) => {
            if (event.currentTarget.contains(event.relatedTarget as Node)) return;
            setTrayDropDay(null);
          },
          onDrop: (event: ReactDragEvent<HTMLElement>) => {
            event.preventDefault();
            const day = dayAtEvent(event);
            setTrayDropDay(null);
            if (day !== null) onTrayDrop(trayDragItem, day);
          },
        }
      : {};

  return (
    <div className="relative" style={{ minWidth: labelWidth + innerWidth }}>
      {/* Full-height resize handle on the labels/timeline divider. Absolute so
          it never joins the row flow; wrapped in a sticky-left rail so it rides
          horizontal scroll with the (sticky) label gutter it resizes. */}
      <div className="pointer-events-none absolute inset-0 z-40" aria-hidden="false">
        <div className="sticky left-0 h-full w-0">
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the label column"
            onPointerDown={onLabelResizeStart}
            style={{ left: labelWidth - 3 }}
            className="pointer-events-auto absolute inset-y-0 w-1.5 cursor-col-resize hover:bg-accent/40 active:bg-accent/60"
            title="Drag to resize · the labels are the timeline's row axis, so they don't collapse"
          />
        </div>
      </div>
      {/* Axis header */}
      <div className="sticky top-0 z-30 flex border-b border-subtle bg-base">
        <div
          style={{ width: labelWidth }}
          // Sticky-left like the row labels below it — the corner cell caps
          // the gutter so month/week ticks slide under it, not through it.
          className="sticky left-0 z-10 shrink-0 border-r border-subtle bg-base px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint"
        >
          Timeline
        </div>
        <div className="relative" style={{ width: innerWidth, height: 40 }}>
          {model.months.map((month) => (
            <span
              key={`m-${month.index}`}
              className="absolute top-1 whitespace-nowrap border-l border-strong pl-1 text-[11px] font-semibold text-fg"
              style={{ left: month.index * dayWidth }}
            >
              {month.label}
            </span>
          ))}
          {weekTicks.map((week) => (
            <span
              key={`w-${week.index}`}
              className="absolute top-5 whitespace-nowrap text-[10px] text-fg-muted"
              style={{ left: week.index * dayWidth + 2 }}
            >
              {week.label}
            </span>
          ))}
          {/* "+1 month" extend caps at both axis ends (spec 78). */}
          <button
            type="button"
            onClick={() => onExtend(ExtendDirection.before)}
            title="Extend the timeline one month earlier"
            aria-label="Extend the timeline one month earlier"
            className="absolute inset-y-0 left-0 z-10 flex w-5 items-center justify-center border-r border-dashed border-strong/70 bg-surface/80 text-fg-muted hover:bg-surface hover:text-accent-text cursor-pointer"
          >
            <Plus size={12} aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => onExtend(ExtendDirection.after)}
            title="Extend the timeline one month later"
            aria-label="Extend the timeline one month later"
            className="absolute inset-y-0 right-0 z-10 flex w-5 items-center justify-center border-l border-dashed border-strong/70 bg-surface/80 text-fg-muted hover:bg-surface hover:text-accent-text cursor-pointer"
          >
            <Plus size={12} aria-hidden />
          </button>
        </div>
      </div>

      {/* Body: containers + gridlines behind, positioned bars above, connectors on top */}
      <div
        ref={bodyRef}
        className={`relative${band ? " select-none" : ""}`}
        onMouseDown={bandStart}
        {...trayTargetProps}
      >
        {band && (
          <div
            className="pointer-events-none absolute z-30 rounded-sm border border-accent/70 bg-accent/10"
            style={{
              left: Math.min(band.x0, band.x1),
              top: Math.min(band.y0, band.y1),
              width: Math.abs(band.x1 - band.x0),
              height: Math.abs(band.y1 - band.y0),
            }}
            aria-hidden
          />
        )}
        {/* Child-container boxes — lowest layer; an epic container drag
            translates its box by the same live delta as the bars (spec 81). */}
        {containerRegions.length > 0 && (
          <div
            className="pointer-events-none absolute inset-y-0 z-0"
            style={{ left: labelWidth, width: innerWidth }}
            aria-hidden
          >
            {containerRegions.map((region) => {
              const delta = epicDrag?.epicId === region.epicId ? epicDrag.delta : 0;
              return (
                <div
                  key={region.epicId}
                  className="absolute rounded-lg border border-strong/40 bg-elevated/15"
                  style={{
                    left: (region.startIndex + delta) * dayWidth,
                    width: region.rightX - region.startIndex * dayWidth,
                    top: region.rowIndex * ROADMAP_ROW_H,
                    height: region.rowCount * ROADMAP_ROW_H,
                  }}
                />
              );
            })}
          </div>
        )}
        <div
          className="pointer-events-none absolute inset-y-0 z-0"
          style={{ left: labelWidth, width: innerWidth }}
        >
          {weekTicks.map((week) => (
            <div
              key={`g-${week.index}`}
              className="absolute inset-y-0 border-l border-subtle/50"
              style={{ left: week.index * dayWidth }}
            />
          ))}
          {model.todayIndex !== null && (
            <div
              className="absolute inset-y-0 border-l-2 border-accent/60"
              style={{ left: model.todayIndex * dayWidth }}
              title="Today"
            />
          )}
          {trayDropDay !== null && (
            <div
              className="absolute inset-y-0 z-20 border-l-2 border-dashed border-accent-hover/80"
              style={{ left: trayDropDay * dayWidth }}
            />
          )}
        </div>

        <div className="relative z-10">
          {visibleRows.map((row) => (
            <BarRow
              key={row.item.id}
              row={row}
              innerWidth={innerWidth}
              dayWidth={dayWidth}
              labelWidth={labelWidth}
              canEdit={canEdit}
              drag={drag}
              domainStart={model.domainStart}
              showConnectors={showConnectors}
              visibleIds={visibleIds}
              collapsed={collapsedEpicIds.has(row.item.id)}
              soloed={soloIds.has(row.item.id)}
              isMember={memberIds.has(row.item.id)}
              onToggleMember={onToggleMember}
              selected={selectedIds.has(row.item.id)}
              onSelectRow={onSelectRow}
              containerDelta={
                epicDrag && row.parentEpicId === epicDrag.epicId ? epicDrag.delta : null
              }
              progress={rowBarProgress(row, timelogByItem, rollupByItem)}
              canReorder={canReorder}
              reorderTarget={
                rowDrag !== null &&
                rowDrag.item.id !== row.item.id &&
                isRoadmapSibling(rowDrag, row)
              }
              reorderIndicator={dropIndicator?.id === row.item.id ? dropIndicator.before : null}
              reordering={reorderState?.row.item.id === row.item.id}
              onRowDragStart={() => setRowDrag(row)}
              onRowDragEnd={endRowDrag}
              onRowDragOver={(before) => setRowDrop({ id: row.item.id, before })}
              onRowDrop={(before) => {
                if (rowDrag) onReorderRow(rowDrag, row, before);
                endRowDrag();
              }}
              onToggleCollapse={onToggleCollapse}
              onToggleSolo={onToggleSolo}
              onContextMenu={onContextMenu}
              onHoverStart={scheduleHover}
              onHoverMove={moveHover}
              onHoverEnd={clearHover}
            />
          ))}
          {/* Open lane below the last row — drop space for tray scheduling. */}
          {canEdit && <div style={{ height: ROADMAP_ROW_H }} aria-hidden />}
        </div>

        {/* Connectors read the COMMITTED model spans, so during an epic
            container drag they lag behind the translated child bars until the
            drop commits — accepted (spec 81). */}
        {(showConnectors || rubber) && (
          <div
            className="pointer-events-none absolute top-0 z-20"
            style={{ left: labelWidth, width: innerWidth }}
          >
            <Connectors
              rows={visibleRows}
              dayWidth={dayWidth}
              rowHeight={ROADMAP_ROW_H}
              width={innerWidth}
              showEdges={showConnectors}
              rubber={rubber}
              onEdgeClick={canEdit ? onEdgeClick : undefined}
            />
          </div>
        )}
      </div>

      {/* Hover info card — fixed, viewport-clamped, pointer-events-none,
          above the connector overlay. Never shown mid-gesture. */}
      {hover && !dragActive && (
        <RoadmapHoverCard
          row={hover.row}
          anchor={hover.anchor}
          timelog={timelogByItem?.[hover.row.item.id]}
          rollup={rollupByItem?.[hover.row.item.id]}
        />
      )}
    </div>
  );
}
