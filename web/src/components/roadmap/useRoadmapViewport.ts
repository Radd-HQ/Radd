/** Roadmap pane navigation: MIDDLE-mouse drag pans both axes (pointer-captured);
 *  CTRL/META+wheel zooms the day width anchored at the cursor (plain wheel still
 *  scrolls); `zoomBy` backs the toolbar ± buttons, anchored at the viewport
 *  center. Listeners live on the pane, and pan uses a button bars, labels and
 *  tray drags never use, so those gestures are untouched.
 *
 *  The zoom is two-axis (RADD-1520): below the default day width the row pitch
 *  shrinks with it (`roadmapRowMetrics`), so the scroll correction anchors the
 *  ROW under the cursor as well as the day. */

import { useCallback, useEffect, useRef, type RefObject } from "react";
import { ROADMAP_ZOOM_WHEEL_FACTOR } from "../../lib/constants";
import { clampDayWidth, roadmapRowMetrics } from "./roadmap-model";

export function useRoadmapViewport(
  scrollRef: RefObject<HTMLDivElement | null>,
  labelWidth: number,
  /** The sticky axis header's height — rows start below it in the scroll content. */
  axisHeight: number,
  dayWidth: number,
  setDayWidth: (width: number) => void,
) {
  // Live values for the non-React wheel/pointer listeners.
  const dayWidthRef = useRef(dayWidth);
  dayWidthRef.current = dayWidth;
  const labelWidthRef = useRef(labelWidth);
  labelWidthRef.current = labelWidth;
  const axisHeightRef = useRef(axisHeight);
  axisHeightRef.current = axisHeight;

  /** Zoom so the day at `anchorX` and the row at `anchorY` (px from the pane's
   *  top-left; default = the centre of the visible timeline) stay under that
   *  point. */
  const zoomBy = useCallback(
    (factor: number, anchorX?: number, anchorY?: number) => {
      const el = scrollRef.current;
      if (!el) return;
      const oldW = dayWidthRef.current;
      const newW = clampDayWidth(oldW * factor);
      if (newW === oldW) return;
      const gutter = labelWidthRef.current;
      const header = axisHeightRef.current;
      const ax = anchorX ?? gutter + (el.clientWidth - gutter) / 2;
      const ay = anchorY ?? header + (el.clientHeight - header) / 2;
      // Content position of the anchored day / row, in day and row units.
      const day = (el.scrollLeft + ax - gutter) / oldW;
      const oldRowH = roadmapRowMetrics(oldW).rowH;
      const newRowH = roadmapRowMetrics(newW).rowH;
      const row = (el.scrollTop + ay - header) / oldRowH;
      setDayWidth(newW);
      // The scroll correction uses the NEW sizes directly — no need to wait
      // for the re-render, scroll metrics are independent of paint.
      requestAnimationFrame(() => {
        el.scrollLeft = Math.max(0, day * newW + gutter - ax);
        if (newRowH !== oldRowH) el.scrollTop = Math.max(0, row * newRowH + header - ay);
      });
    },
    [scrollRef, setDayWidth],
  );

  // Middle-mouse pan.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let pan: { x: number; y: number; left: number; top: number } | null = null;
    const down = (event: PointerEvent) => {
      if (event.button !== 1) return;
      event.preventDefault(); // suppress browser middle-click autoscroll
      pan = { x: event.clientX, y: event.clientY, left: el.scrollLeft, top: el.scrollTop };
      el.setPointerCapture(event.pointerId);
      el.style.cursor = "grabbing";
    };
    const move = (event: PointerEvent) => {
      if (!pan) return;
      el.scrollLeft = pan.left - (event.clientX - pan.x);
      el.scrollTop = pan.top - (event.clientY - pan.y);
    };
    const end = (event: PointerEvent) => {
      if (event.button !== 1 || !pan) return;
      pan = null;
      el.style.cursor = "";
      if (el.hasPointerCapture(event.pointerId)) el.releasePointerCapture(event.pointerId);
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
    return () => {
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", end);
      el.removeEventListener("pointercancel", end);
    };
  }, [scrollRef]);

  // Ctrl+wheel zoom, anchored at the cursor. Non-passive: we own the gesture
  // (otherwise the browser page-zooms). rAF-coalesced against wheel floods.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let queued: { deltaY: number; x: number; y: number } | null = null;
    const wheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const first = queued === null;
      const rect = el.getBoundingClientRect();
      queued = {
        deltaY: (queued?.deltaY ?? 0) + event.deltaY,
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      if (!first) return;
      requestAnimationFrame(() => {
        if (!queued) return;
        const steps = -queued.deltaY / 100;
        zoomBy(ROADMAP_ZOOM_WHEEL_FACTOR ** steps, queued.x, queued.y);
        queued = null;
      });
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [scrollRef, zoomBy]);

  return { zoomBy };
}
