/** Roadmap geometry: bar sizes, hit zones, px ↔ day-index conversion (spec 77). */

// ---------------------------------------------------------------------------
// Geometry: px ↔ day-index conversion (zoom = configurable day width, spec 77)
// ---------------------------------------------------------------------------

// Vertical bar/row geometry (bar-presentation polish): ONE source
// shared by the bar rows, the connector overlay, the drag ghosts/slabs, and
// the child-container region so nothing misaligns. Bar heights are fixed px —
// independent of the day-width zoom.

/** Leaf (issue/subtask) bar height. */
export const ROADMAP_LEAF_BAR_H = 30;
/** Epic bar height — a touch taller than leaves so containers read as such. */
export const ROADMAP_EPIC_BAR_H = 34;
/** Breathing room above/below the tallest bar in a row. */
export const ROADMAP_ROW_PAD_Y = 5;
/** Row pitch — label cells, lanes, connector Y math, and the drop lane. */
export const ROADMAP_ROW_H = ROADMAP_EPIC_BAR_H + ROADMAP_ROW_PAD_Y * 2;
/** Bars at least this wide draw their info (title + priority + assignee)
 *  INSIDE the bar; narrower bars put the title outside, to the right. */
export const ROADMAP_BAR_INFO_MIN_PX = 90;

/** The bar height for a row — epics are taller than leaves. */
export function roadmapBarHeight(isEpic: boolean): number {
  return isEpic ? ROADMAP_EPIC_BAR_H : ROADMAP_LEAF_BAR_H;
}

// Narrow-bar rendering (revised in the progress/hover-card pass):
// a bar's rendered width IS its logical width — the minimum is ONE DAY by
// construction (endIndex >= startIndex), so short tasks are never exaggerated.
// ONE clamp remains: an absolute grab floor of `ROADMAP_BAR_MIN_PX` that only
// engages when dayWidth < that floor (the 6px compact and 9px default zooms'
// one-day bars). The floor is PRESENTATION ONLY (logical day indices/dates are
// untouched, and drag commits compute from snapped pointer DELTAS, never the
// rendered width, so a clamped bar moves and resizes correctly). Everything
// hanging off a bar's right edge (the depends chip, the ○ link handle,
// connector sources, the rubber-band anchor) positions off the CLAMPED edge
// via `barRenderWidth`/`barRenderRightX`.

/** Absolute grab floor — bars never render narrower than this even when one
 *  day is fewer px (compact zooms). Below ~10px even a bar whose resize zones
 *  sit fully outside is too small to click or grab. */
export const ROADMAP_BAR_MIN_PX = 10;
/** Rendered widths below this get the narrow-bar hit treatment: slimmer
 *  inside resize zones that extend OUTSIDE the bar, and the ○ link handle
 *  pushed fully clear of the bar + its outside zone. */
export const ROADMAP_NARROW_BAR_PX = 48;
/** Edge resize grab-zone width INSIDE a normal-width bar (spec 77). */
export const ROADMAP_RESIZE_EDGE_PX = 6;
/** Narrow bars: the inside slice of each edge zone shrinks to this. */
export const ROADMAP_RESIZE_EDGE_NARROW_PX = 4;
/** Narrow bars: each edge zone also extends this far OUTSIDE the bar
 *  (invisible hit area, ew-resize cursor). */
export const ROADMAP_RESIZE_EDGE_OUTSET_PX = 6;
/** Minimum clean body-move area a bar must keep between its resize zones. */
export const ROADMAP_BAR_MIN_BODY_PX = 16;
/** Below this rendered width even the slim inside slices would eat into the
 *  minimum body area — the resize zones move FULLY outside the bar instead,
 *  leaving the whole bar as body (one-day bars at every zoom land here). */
export const ROADMAP_TINY_BAR_PX =
  ROADMAP_RESIZE_EDGE_NARROW_PX * 2 + ROADMAP_BAR_MIN_BODY_PX;
/** The ○ link handle's square hit target — the visible dot is smaller,
 *  centered inside it. */
export const ROADMAP_LINK_HANDLE_HIT_PX = 16;

/** The rendered bar width for a span: the logical width (>= one day), floored
 *  at the absolute grab minimum. */
export function barRenderWidth(startIndex: number, endIndex: number, dayWidth: number): number {
  return Math.max((endIndex - startIndex + 1) * dayWidth, ROADMAP_BAR_MIN_PX);
}

/** A bar's edge resize-zone layout: each zone covers `insidePx` inside the
 *  bar edge plus `outsidePx` beyond it (the ○ handle and the depends chip
 *  shift right by `outsidePx` to stay clear). */
export interface BarHitZones {
  insidePx: number;
  outsidePx: number;
}

/** Three tiers by rendered width: normal (6px inside), narrow (4px inside +
 *  6px outside), tiny (zones fully outside — the whole bar is body-move
 *  area, since even 4px slices would leave < ROADMAP_BAR_MIN_BODY_PX). */
export function barHitZones(renderWidth: number): BarHitZones {
  if (renderWidth >= ROADMAP_NARROW_BAR_PX) {
    return { insidePx: ROADMAP_RESIZE_EDGE_PX, outsidePx: 0 };
  }
  if (renderWidth >= ROADMAP_TINY_BAR_PX) {
    return { insidePx: ROADMAP_RESIZE_EDGE_NARROW_PX, outsidePx: ROADMAP_RESIZE_EDGE_OUTSET_PX };
  }
  return {
    insidePx: 0,
    outsidePx: ROADMAP_RESIZE_EDGE_NARROW_PX + ROADMAP_RESIZE_EDGE_OUTSET_PX,
  };
}

/** The rendered (clamped) right-edge x of a bar — trailing UI, connector
 *  sources, and the rubber-band anchor hang off THIS, not the logical edge. */
export function barRenderRightX(startIndex: number, endIndex: number, dayWidth: number): number {
  return startIndex * dayWidth + barRenderWidth(startIndex, endIndex, dayWidth);
}

/** The day cell containing a lane-local x (drop targeting). */
export function dayFromX(x: number, dayWidth: number): number {
  return Math.floor(x / dayWidth);
}

/** Snapped whole-day delta for a pixel drag distance (move/resize gestures). */
export function dayDeltaFromDx(dx: number, dayWidth: number): number {
  return Math.round(dx / dayWidth);
}

export function clampDay(day: number, domainDays: number): number {
  return Math.max(0, Math.min(day, domainDays - 1));
}

export interface RoadmapSpan {
  startIndex: number;
  endIndex: number;
}

/** A whole-bar move: duration preserved, clamped inside the padded domain. */
export function moveSpan(span: RoadmapSpan, delta: number, domainDays: number): RoadmapSpan {
  const duration = span.endIndex - span.startIndex;
  const start = Math.max(0, Math.min(span.startIndex + delta, domainDays - 1 - duration));
  return { startIndex: start, endIndex: start + duration };
}

export const DragEdge = { start: "start", end: "end" } as const;
export type DragEdgeValue = (typeof DragEdge)[keyof typeof DragEdge];

/** An edge resize: the moved edge never crosses the other (target >= start). */
export function resizeSpan(
  span: RoadmapSpan,
  edge: DragEdgeValue,
  delta: number,
  domainDays: number,
): RoadmapSpan {
  if (edge === DragEdge.start) {
    const start = Math.max(0, Math.min(span.startIndex + delta, span.endIndex));
    return { startIndex: start, endIndex: span.endIndex };
  }
  const end = Math.min(Math.max(span.endIndex + delta, span.startIndex), domainDays - 1);
  return { startIndex: span.startIndex, endIndex: end };
}
