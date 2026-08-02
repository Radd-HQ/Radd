import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import { ROADMAP_EDGE_AUTOSCROLL_PX } from "../../lib/constants";
import {
  DragEdge,
  dayDeltaFromDx,
  moveSpan,
  resizeSpan,
  type DragEdgeValue,
  type RoadmapRow,
  type RoadmapSpan,
} from "./roadmap-model";

/**
 * The roadmap's pointer-event gesture machine (specs 77 + 78): one hook
 * instance per timeline owns the single live drag — bar MOVE (day-snapped
 * ghost, duration preserved), edge RESIZE (either edge, target >= start), and
 * LINK creation (rubber band from the ○ handle to another bar). Pointer capture
 * keeps the stream on the pressed element; a 4px threshold separates click
 * (open the peek panel — the caller's onClick consumes `consumeDragClick`)
 * from drag. All day math delegates to the pure model helpers.
 *
 * Spec 78: drags near the scroll pane's horizontal edges auto-scroll via a
 * requestAnimationFrame loop, and once the pane is pinned at an end the loop
 * asks the owner to EXTEND the domain that direction — deltas are
 * scroll-compensated so the ghost tracks the pointer through both. When a
 * before-extension shifts the domain start, the owner calls `shiftDomain` so
 * the live drag's day indices stay anchored to the same calendar dates.
 * Alt held at drop is reported to `onCommitSpan` along with the gesture mode:
 * "just this bar" — it skips an epic's children (spec 81) AND the dependency
 * cascade. Alt is also tracked LIVE in the state so an epic container drag's
 * child translation can collapse to just the bar while Alt is down.
 *
 * Spec 82 follow-up: a bar-BODY drag is AXIS-AWARE — the instant it crosses
 * the threshold, the dominant axis locks the gesture: |dx| >= |dy| stays the
 * horizontal date move, a vertical win becomes a row REORDER (only when
 * `reorderEnabled`). In reorder mode the bar holds its x, the state carries
 * the body-local pointer, and the drop reports through `onReorderDrop` — the
 * owner maps it to a sibling row half and persists via the label-drag path.
 */

export const BarDragMode = {
  move: "move",
  resizeStart: "resizeStart",
  resizeEnd: "resizeEnd",
  link: "link",
  /** Vertical bar-body drag → sibling row reorder (spec 82 follow-up). Never
   *  begun directly — a `move` re-classifies at the threshold. */
  reorder: "reorder",
} as const;
export type BarDragModeValue = (typeof BarDragMode)[keyof typeof BarDragMode];

/** Movement below this (px, either axis) is a click, not a drag. */
const DRAG_THRESHOLD_PX = 4;
/** Auto-scroll speed while a ghost hugs a pane edge (px per animation frame). */
const AUTOSCROLL_PX_PER_FRAME = 14;
/** Minimum pause between two auto-extensions while pinned at an edge. */
const AUTOEXTEND_HOLD_MS = 600;

/** Bars carry their item id here — link drops resolve targets through it. */
export const BAR_ITEM_ATTR = "data-bar-item";

export interface BarDragState {
  mode: BarDragModeValue;
  row: RoadmapRow;
  /** True once the pointer moved past the click threshold. */
  started: boolean;
  /** Snapped whole-day delta (move/resize), scroll-compensated. */
  dayDelta: number;
  /** Alt currently held (live, from the last pointer event) — an epic
   *  container drag renders "just this bar" while it's down (spec 81). */
  alt: boolean;
  /** Lane-local pointer position (link + reorder modes) — the rubber band's
   *  free end / the hovered-row probe (its y is body-local). */
  pointer: { x: number; y: number } | null;
  /** The bar currently under the pointer (link mode), never the source. */
  targetId: string | null;
}

interface GestureHandlers {
  onPointerDown?: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerMove?: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerUp?: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerCancel?: (event: ReactPointerEvent<HTMLElement>) => void;
}

export interface BarDrag {
  state: BarDragState | null;
  /** Ghost span for `row` while a live move/resize drag targets it, else null. */
  previewSpan: (row: RoadmapRow) => RoadmapSpan | null;
  /** True exactly once after a completed drag — bar onClick consumes it to skip the peek. */
  consumeDragClick: () => boolean;
  /**
   * The domain start moved `days` earlier mid-drag (a before-extension): shift
   * the live drag's row indices so the ghost stays on the same calendar dates.
   */
  shiftDomain: (days: number) => void;
  barProps: (row: RoadmapRow) => GestureHandlers;
  edgeProps: (row: RoadmapRow, edge: DragEdgeValue) => GestureHandlers;
  linkProps: (row: RoadmapRow) => GestureHandlers;
}

export const ExtendDirection = { before: "before", after: "after" } as const;
export type ExtendDirectionValue = (typeof ExtendDirection)[keyof typeof ExtendDirection];

/** What `onCommitSpan` learns about the drop beyond the span itself. */
export interface CommitModifiers {
  /** Alt was held at drop — "just this bar": skip an epic's children (spec 81)
   *  AND the dependency cascade (spec 78). */
  alt: boolean;
  /** Which gesture committed: an epic BODY move carries its children. */
  mode: BarDragModeValue;
}

export interface BarDragOptions {
  enabled: boolean;
  dayWidth: number;
  domainDays: number;
  /** The full-width timeline body — lane-local x is offset by the label gutter. */
  bodyRef: RefObject<HTMLDivElement | null>;
  /** LIVE label-gutter width. Read through optionsRef so a resize mid-session
   *  cannot leave the hit-testing on a stale offset. */
  labelWidth: number;
  /** The horizontal scroll pane — edge auto-scroll + extension (spec 78). */
  scrollRef: RefObject<HTMLElement | null>;
  onCommitSpan: (row: RoadmapRow, span: RoadmapSpan, modifiers: CommitModifiers) => void;
  /** Link drop (spec 78: opens the type popover at the drop point). */
  onCreateLink: (row: RoadmapRow, targetItemId: string, x: number, y: number) => void;
  /** The drag is pinned at a pane end — grow the domain that direction. */
  onAutoExtend: (direction: ExtendDirectionValue) => void;
  /** Spec 82 follow-up: a vertical bar-body drag becomes a sibling row
   *  reorder. False = today's horizontal-only body gesture, exactly. */
  reorderEnabled: boolean;
  /** Reorder drop at body-local y — the owner resolves the sibling row half
   *  (pure `rowDropFromY`) and persists via the SAME path as the label drag.
   *  An invalid target commits nothing. */
  onReorderDrop: (row: RoadmapRow, bodyY: number) => void;
}

const previewFor = (state: BarDragState, domainDays: number): RoadmapSpan | null => {
  const base: RoadmapSpan = { startIndex: state.row.startIndex, endIndex: state.row.endIndex };
  switch (state.mode) {
    case BarDragMode.move:
      return moveSpan(base, state.dayDelta, domainDays);
    case BarDragMode.resizeStart:
      return resizeSpan(base, DragEdge.start, state.dayDelta, domainDays);
    case BarDragMode.resizeEnd:
      return resizeSpan(base, DragEdge.end, state.dayDelta, domainDays);
    default:
      return null;
  }
};

export function useBarDrag(options: BarDragOptions): BarDrag {
  const [state, renderState] = useState<BarDragState | null>(null);
  // Ref mirror: pointer handlers read/write the CURRENT state without stale
  // closures; the useState copy only drives rendering.
  const stateRef = useRef<BarDragState | null>(null);
  const originRef = useRef({ x: 0, y: 0 });
  const originScrollLeftRef = useRef(0);
  const pointerRef = useRef({ x: 0, y: 0 });
  // Alt from the LAST pointer event — applyPointer also runs from the
  // auto-scroll rAF loop, which has no event to read the key from.
  const lastAltRef = useRef(false);
  const wasDragRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const set = (next: BarDragState | null) => {
    stateRef.current = next;
    renderState(next);
  };

  const begin = (event: ReactPointerEvent<HTMLElement>, row: RoadmapRow, mode: BarDragModeValue) => {
    if (!optionsRef.current.enabled || event.button !== 0 || stateRef.current) return;
    // Derived epic spans track their children — not directly draggable.
    if (mode !== BarDragMode.link && row.derived) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    originRef.current = { x: event.clientX, y: event.clientY };
    pointerRef.current = { x: event.clientX, y: event.clientY };
    lastAltRef.current = event.altKey;
    originScrollLeftRef.current = optionsRef.current.scrollRef.current?.scrollLeft ?? 0;
    set({ mode, row, started: false, dayDelta: 0, alt: event.altKey, pointer: null, targetId: null });
  };

  /** Re-derive the drag state from the latest pointer position — called by
   *  pointermove AND the auto-scroll loop (scrolling moves no pointer). */
  const applyPointer = (clientX: number, clientY: number, allowStart: boolean) => {
    const current = stateRef.current;
    if (!current) return;
    const { dayWidth, bodyRef, scrollRef } = optionsRef.current;
    const dx = clientX - originRef.current.x;
    const dy = clientY - originRef.current.y;
    const started =
      current.started ||
      (allowStart && (Math.abs(dx) >= DRAG_THRESHOLD_PX || Math.abs(dy) >= DRAG_THRESHOLD_PX));
    if (!started) return;
    // Axis lock (spec 82 follow-up): the instant a bar-BODY drag crosses the
    // threshold, the dominant axis classifies it — |dx| >= |dy| stays the
    // horizontal date move, a vertical win becomes a row REORDER (only when
    // the surface enables it). The mode then holds for the whole gesture (no
    // mid-drag switching); resize and link gestures never re-classify.
    const mode =
      !current.started &&
      current.mode === BarDragMode.move &&
      optionsRef.current.reorderEnabled &&
      Math.abs(dy) > Math.abs(dx)
        ? BarDragMode.reorder
        : current.mode;
    if (mode === BarDragMode.link || mode === BarDragMode.reorder) {
      const rect = bodyRef.current?.getBoundingClientRect();
      const pointer = rect
        ? { x: clientX - rect.left - optionsRef.current.labelWidth, y: clientY - rect.top }
        : current.pointer;
      if (mode === BarDragMode.reorder) {
        // The bar holds its x — only the body-local pointer travels; the
        // owner maps its y to the hovered sibling row half.
        set({ ...current, mode, started, pointer });
        return;
      }
      // Pointer capture swallows enter/leave on other elements — resolve the
      // drop candidate geometrically instead.
      const under = document.elementFromPoint(clientX, clientY);
      const targetId = under?.closest(`[${BAR_ITEM_ATTR}]`)?.getAttribute(BAR_ITEM_ATTR) ?? null;
      set({
        ...current,
        started,
        pointer,
        targetId: targetId === current.row.item.id ? null : targetId,
      });
      return;
    }
    // Move/resize: auto-scrolling shifts the content under a stationary
    // pointer — fold the scroll distance into the drag delta.
    const scrollDx = (scrollRef.current?.scrollLeft ?? 0) - originScrollLeftRef.current;
    set({
      ...current,
      started,
      dayDelta: dayDeltaFromDx(dx + scrollDx, dayWidth),
      alt: lastAltRef.current,
    });
  };

  const onMove = (event: ReactPointerEvent<HTMLElement>) => {
    pointerRef.current = { x: event.clientX, y: event.clientY };
    lastAltRef.current = event.altKey;
    applyPointer(event.clientX, event.clientY, true);
  };

  const finish = (event: ReactPointerEvent<HTMLElement>) => {
    const current = stateRef.current;
    if (!current) return;
    set(null);
    if (!current.started) return; // plain click — the bar's onClick opens the peek
    const { domainDays, onCommitSpan, onCreateLink, onReorderDrop, bodyRef } = optionsRef.current;
    if (current.mode === BarDragMode.link) {
      // The trailing click lands on the ○ handle, not the bar — no suppression.
      if (current.targetId) {
        onCreateLink(current.row, current.targetId, event.clientX, event.clientY);
      }
      return;
    }
    // Move/resize/reorder: the trailing click fires on the bar — flag it for
    // onClick so a completed drag never opens the peek panel.
    wasDragRef.current = true;
    if (current.mode === BarDragMode.reorder) {
      // Hand the drop's body-local y to the owner — it resolves the sibling
      // row half and persists via the SAME path as the label drag; an invalid
      // target commits nothing (the bar never left its x anyway).
      const rect = bodyRef.current?.getBoundingClientRect();
      if (rect) onReorderDrop(current.row, event.clientY - rect.top);
      return;
    }
    const span = previewFor(current, domainDays);
    if (span && (span.startIndex !== current.row.startIndex || span.endIndex !== current.row.endIndex)) {
      onCommitSpan(current.row, span, { alt: event.altKey, mode: current.mode });
    }
  };

  const cancel = () => set(null);

  // While a drag is live, pin the cursor + disable text selection globally
  // (pointer capture doesn't lock the cursor to the pressed element).
  useEffect(() => {
    if (!state?.started) return;
    document.body.style.cursor =
      state.mode === BarDragMode.move || state.mode === BarDragMode.reorder
        ? "grabbing"
        : state.mode === BarDragMode.link
          ? "crosshair"
          : "ew-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [state?.started, state?.mode]);

  // Edge auto-scroll + live extension (spec 78): while the drag hugs a pane
  // edge, scroll toward it; once the pane is pinned at that end, ask the owner
  // to extend the domain (throttled) so the ghost can keep going.
  const started = state?.started ?? false;
  useEffect(() => {
    if (!started) return;
    let frame = 0;
    let lastExtend = 0;
    const step = () => {
      const pane = optionsRef.current.scrollRef.current;
      // Reorder is a vertical gesture — no horizontal auto-scroll/extension.
      if (pane && stateRef.current && stateRef.current.mode !== BarDragMode.reorder) {
        const rect = pane.getBoundingClientRect();
        const { x, y } = pointerRef.current;
        const now = performance.now();
        const maxScroll = pane.scrollWidth - pane.clientWidth;
        if (x >= rect.right - ROADMAP_EDGE_AUTOSCROLL_PX) {
          if (pane.scrollLeft >= maxScroll - 1) {
            if (now - lastExtend >= AUTOEXTEND_HOLD_MS) {
              lastExtend = now;
              optionsRef.current.onAutoExtend(ExtendDirection.after);
            }
          } else {
            pane.scrollLeft = Math.min(maxScroll, pane.scrollLeft + AUTOSCROLL_PX_PER_FRAME);
            applyPointer(x, y, false);
          }
        } else if (x <= rect.left + ROADMAP_EDGE_AUTOSCROLL_PX) {
          if (pane.scrollLeft <= 1) {
            if (now - lastExtend >= AUTOEXTEND_HOLD_MS) {
              lastExtend = now;
              optionsRef.current.onAutoExtend(ExtendDirection.before);
            }
          } else {
            pane.scrollLeft = Math.max(0, pane.scrollLeft - AUTOSCROLL_PX_PER_FRAME);
            applyPointer(x, y, false);
          }
        }
      }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [started]);

  const gestureProps = (row: RoadmapRow, mode: BarDragModeValue): GestureHandlers =>
    options.enabled
      ? {
          onPointerDown: (event) => begin(event, row, mode),
          onPointerMove: onMove,
          onPointerUp: finish,
          onPointerCancel: cancel,
        }
      : {};

  return {
    state,
    previewSpan: (row) =>
      state?.started && state.mode !== BarDragMode.link && state.row.item.id === row.item.id
        ? previewFor(state, options.domainDays)
        : null,
    consumeDragClick: () => {
      const was = wasDragRef.current;
      wasDragRef.current = false;
      return was;
    },
    shiftDomain: (days) => {
      const current = stateRef.current;
      if (!current || days === 0) return;
      set({
        ...current,
        row: {
          ...current.row,
          startIndex: current.row.startIndex + days,
          endIndex: current.row.endIndex + days,
        },
      });
    },
    barProps: (row) => gestureProps(row, BarDragMode.move),
    edgeProps: (row, edge) =>
      gestureProps(row, edge === DragEdge.start ? BarDragMode.resizeStart : BarDragMode.resizeEnd),
    linkProps: (row) => gestureProps(row, BarDragMode.link),
  };
}
