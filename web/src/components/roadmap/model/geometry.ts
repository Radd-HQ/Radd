/** Roadmap geometry: bar sizes, hit zones, px ↔ day-index conversion (spec 77). */

// Vertical bar/row geometry — ONE source for bar rows, connectors, drag ghosts
// and container regions so nothing misaligns. These are the COMFORTABLE sizes,
// at and above the default day width; zooming out below it scales them down
// together (`roadmapRowMetrics` in ./zoom.ts, RADD-1520) — read the live
// metrics, never these constants, anywhere a row's height matters.

/** Leaf (issue/subtask) bar height. */
export const ROADMAP_LEAF_BAR_H = 30;
/** Epic bar height — a touch taller than leaves so containers read as such. */
export const ROADMAP_EPIC_BAR_H = 34;
/** Breathing room above/below the tallest bar in a row. */
const ROADMAP_ROW_PAD_Y = 5;
/** Row pitch — label cells, lanes, connector Y math, and the drop lane. */
export const ROADMAP_ROW_H = ROADMAP_EPIC_BAR_H + ROADMAP_ROW_PAD_Y * 2;
/** The sticky axis header (months + week ticks). */
export const ROADMAP_AXIS_H = 40;
/** The cycle strip under the axis (RADD-1511): one labelled band per dated
 *  cycle; present only when a cycle overlaps the domain. */
export const ROADMAP_CYCLE_STRIP_H = 18;

/** The header's height — rows start below it in the scroll content. */
export function roadmapAxisHeight(hasCycleStrip: boolean): number {
  return ROADMAP_AXIS_H + (hasCycleStrip ? ROADMAP_CYCLE_STRIP_H : 0);
}
/** Bars at least this wide draw their FULL info (title + priority + assignee)
 *  inside the bar. */
export const ROADMAP_BAR_INFO_MIN_PX = 90;
/** Bars at least this wide (under the full tier) draw the COMPACT tier: the
 *  priority icon and the assignee avatar in their pill, centred, no title.
 *  At the default zoom a one-week bar is 63px, so a blank bar was the common
 *  case, not the edge (RADD-1509). The pill is 4+14+4+20+4 = 46px, hence 48.
 *  Narrower bars draw nothing — the hover card covers them; a title OUTSIDE
 *  the bar was considered and dropped: the sticky label gutter already names
 *  every row, and an outside title collides with the next bar. */
export const ROADMAP_BAR_COMPACT_MIN_PX = 48;
/** Height gates (RADD-1520): bars shrink with the zoom, and chrome that cannot
 *  fit steps down rather than clipping. The title line (13px text) needs 22px;
 *  the icon pill (14px icon + its padding) 18px; the 20px avatar in its pill
 *  26px — below that the pill keeps the icon alone. */
export const ROADMAP_BAR_INFO_MIN_H = 22;
export const ROADMAP_BAR_PILL_MIN_H = 18;
export const ROADMAP_BAR_AVATAR_MIN_H = 26;

export const RoadmapBarInfoTier = { full: "full", compact: "compact", none: "none" } as const;
export type RoadmapBarInfoTierValue = (typeof RoadmapBarInfoTier)[keyof typeof RoadmapBarInfoTier];

/** Which in-bar info tier a rendered width AND height earn. */
export function barInfoTier(renderWidth: number, barHeight: number): RoadmapBarInfoTierValue {
  if (renderWidth >= ROADMAP_BAR_INFO_MIN_PX && barHeight >= ROADMAP_BAR_INFO_MIN_H) {
    return RoadmapBarInfoTier.full;
  }
  if (renderWidth >= ROADMAP_BAR_COMPACT_MIN_PX && barHeight >= ROADMAP_BAR_PILL_MIN_H) {
    return RoadmapBarInfoTier.compact;
  }
  return RoadmapBarInfoTier.none;
}

/** Whether the assignee avatar fits the bar's pill at this height. */
export function barShowsAvatar(barHeight: number): boolean {
  return barHeight >= ROADMAP_BAR_AVATAR_MIN_H;
}

// A bar's rendered width IS its logical width (>= one day). The one clamp is
// the grab floor `ROADMAP_BAR_MIN_PX`, which engages only when a day is
// narrower than it and is PRESENTATION ONLY: commits compute from snapped
// pointer deltas, never the rendered width. Everything hanging off a bar's
// right edge (depends chip, ○ handle, connector sources, rubber band)
// positions off the CLAMPED edge via `barRenderWidth`/`barRenderRightX`.

/** Absolute grab floor — bars never render narrower than this even when one
 *  day is fewer px (compact zooms). Below ~10px even a bar whose resize zones
 *  sit fully outside is too small to click or grab. */
const ROADMAP_BAR_MIN_PX = 10;
/** Rendered widths below this get the narrow-bar hit treatment: slimmer
 *  inside resize zones that extend OUTSIDE the bar, and the ○ link handle
 *  pushed fully clear of the bar + its outside zone. */
const ROADMAP_NARROW_BAR_PX = 48;
/** Edge resize grab-zone width INSIDE a normal-width bar (spec 77). */
const ROADMAP_RESIZE_EDGE_PX = 6;
/** Narrow bars: the inside slice of each edge zone shrinks to this. */
const ROADMAP_RESIZE_EDGE_NARROW_PX = 4;
/** Narrow bars: each edge zone also extends this far OUTSIDE the bar
 *  (invisible hit area, ew-resize cursor). */
const ROADMAP_RESIZE_EDGE_OUTSET_PX = 6;
/** Minimum clean body-move area a bar must keep between its resize zones. */
const ROADMAP_BAR_MIN_BODY_PX = 16;
/** Below this rendered width even the slim inside slices would eat into the
 *  minimum body area — the resize zones move FULLY outside the bar instead,
 *  leaving the whole bar as body (one-day bars at every zoom land here). */
const ROADMAP_TINY_BAR_PX =
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
interface BarHitZones {
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
