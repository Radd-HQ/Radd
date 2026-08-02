/** Viewport navigation for the roadmap pane (DCC-style, 2026-08-01):
 *
 *  - MIDDLE-MOUSE drag pans the scroll pane both axes (grabbing cursor,
 *    pointer-captured so fast drags don't drop).
 *  - CTRL+WHEEL zooms the day width continuously, anchored at the cursor —
 *    the day under the pointer stays put while the axis stretches around it.
 *    Plain wheel keeps native scrolling.
 *  - `zoomBy` backs the toolbar ± buttons (anchored at the viewport center).
 *
 *  Zoom is continuous within [ROADMAP_DAY_WIDTH_MIN, MAX]; the preset Select
 *  keeps working (it just sets exact widths). All listeners live on the pane,
 *  so bars/labels/tray drags are untouched — pan uses a button they never do.
 */

import { useCallback, useEffect, useRef, type RefObject } from "react";
import {
  ROADMAP_DAY_WIDTH_MAX,
  ROADMAP_DAY_WIDTH_MIN,
  ROADMAP_ZOOM_WHEEL_FACTOR,
} from "../../lib/constants";

const clampWidth = (width: number) =>
  Math.min(ROADMAP_DAY_WIDTH_MAX, Math.max(ROADMAP_DAY_WIDTH_MIN, width));

export function useRoadmapViewport(
  scrollRef: RefObject<HTMLDivElement | null>,
  labelWidth: number,
  dayWidth: number,
  setDayWidth: (width: number) => void,
) {
  // Live values for the non-React wheel/pointer listeners.
  const dayWidthRef = useRef(dayWidth);
  dayWidthRef.current = dayWidth;
  const labelWidthRef = useRef(labelWidth);
  labelWidthRef.current = labelWidth;

  /** Zoom so the day at `anchorViewportX` (px from the pane's left edge;
   *  default = center of the visible timeline) stays under that point. */
  const zoomBy = useCallback(
    (factor: number, anchorViewportX?: number) => {
      const el = scrollRef.current;
      if (!el) return;
      const oldW = dayWidthRef.current;
      const newW = clampWidth(oldW * factor);
      if (newW === oldW) return;
      const gutter = labelWidthRef.current;
      const anchor =
        anchorViewportX ?? gutter + (el.clientWidth - gutter) / 2;
      // Content x of the anchored day, minus the gutter, in day units.
      const day = (el.scrollLeft + anchor - gutter) / oldW;
      setDayWidth(newW);
      // The scroll correction uses the NEW width directly — no need to wait
      // for the re-render, scroll metrics are independent of paint.
      requestAnimationFrame(() => {
        el.scrollLeft = Math.max(0, day * newW + gutter - anchor);
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
    let queued: { deltaY: number; x: number } | null = null;
    const wheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const first = queued === null;
      queued = {
        deltaY: (queued?.deltaY ?? 0) + event.deltaY,
        x: event.clientX - el.getBoundingClientRect().left,
      };
      if (!first) return;
      requestAnimationFrame(() => {
        if (!queued) return;
        const steps = -queued.deltaY / 100;
        zoomBy(ROADMAP_ZOOM_WHEEL_FACTOR ** steps, queued.x);
        queued = null;
      });
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [scrollRef, zoomBy]);

  return { zoomBy };
}
