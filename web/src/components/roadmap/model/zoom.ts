/** Roadmap zoom model (RADD-1520): what ONE day width implies for everything else — the row
 *  pitch and bar heights, which axis tier can carry its labels, which in-row chrome still fits,
 *  and the width that frames a whole domain. Pure; no React. The day width is the only zoom
 *  state, so nothing index-based (group boxes, connectors, drop targets) can disagree with the
 *  rows: they all derive from the same number. */

import {
  ROADMAP_DAY_WIDTH,
  ROADMAP_DAY_WIDTH_MAX,
  ROADMAP_DAY_WIDTH_MIN,
} from "../../../lib/constants";
import { ROADMAP_EPIC_BAR_H, ROADMAP_LEAF_BAR_H, ROADMAP_ROW_H } from "./geometry";
import type { AxisTick } from "./rows";

/** The smallest row pitch: a strip that still shows a bar. The 306-row BNS roadmap is 13.5k px
 *  tall at the comfortable pitch and 2.4k here — an overview, which is what zooming out is for. */
export const ROADMAP_ROW_MIN_H = 8;

export interface RoadmapRowMetrics {
  /** Row pitch — label cells, lanes, connector Y math, the drop lane. Whole px. */
  rowH: number;
  leafBarH: number;
  epicBarH: number;
}

/** Below the default day width the rows shrink by the SAME factor as the days — the board scales
 *  as one surface, the way browser zoom does, which is what Hussein had been using to see a whole
 *  epic group. Above the default the rows keep the comfortable pitch: zooming in is for day
 *  detail, not taller rows. Whole pixels, so `rowIndex * rowH` lands on device pixels at every
 *  level (RADD-1513 is a pitch bug; the metrics must never reintroduce one). */
export function roadmapRowMetrics(dayWidth: number): RoadmapRowMetrics {
  const rowH = Math.max(
    ROADMAP_ROW_MIN_H,
    Math.round(ROADMAP_ROW_H * Math.min(1, dayWidth / ROADMAP_DAY_WIDTH)),
  );
  const scale = rowH / ROADMAP_ROW_H;
  return {
    rowH,
    leafBarH: Math.max(2, Math.round(ROADMAP_LEAF_BAR_H * scale)),
    epicBarH: Math.max(2, Math.round(ROADMAP_EPIC_BAR_H * scale)),
  };
}

/** The label cell's chrome by row pitch: everything (chevron · kind · key · title · chips ·
 *  buttons) needs the 13px text's line plus room; a mini line of nano text needs 14px; below
 *  that the cell draws nothing but keeps its selection tint and tree guide, which still read. */
export const RoadmapLabelTier = { full: "full", mini: "mini", none: "none" } as const;
export type RoadmapLabelTierValue = (typeof RoadmapLabelTier)[keyof typeof RoadmapLabelTier];
export const ROADMAP_LABEL_FULL_MIN_H = 22;
export const ROADMAP_LABEL_MINI_MIN_H = 14;

export function roadmapLabelTier(rowH: number): RoadmapLabelTierValue {
  if (rowH >= ROADMAP_LABEL_FULL_MIN_H) return RoadmapLabelTier.full;
  if (rowH >= ROADMAP_LABEL_MINI_MIN_H) return RoadmapLabelTier.mini;
  return RoadmapLabelTier.none;
}

/** Axis tiers, chosen by what a label needs in px — never by a magic day width. */
export const RoadmapAxisTier = { month: "month", quarter: "quarter", year: "year" } as const;
export type RoadmapAxisTierValue = (typeof RoadmapAxisTier)[keyof typeof RoadmapAxisTier];
export const RoadmapWeekTier = { all: "all", alternate: "alternate", none: "none" } as const;
export type RoadmapWeekTierValue = (typeof RoadmapWeekTier)[keyof typeof RoadmapWeekTier];

/** What one label needs in px, its box included — measured: "Feb 2021" (text-meta semibold,
 *  pl-1 + border) is 57px, "Q1 2021" 50–55px, "2021" ~35px, "Oct 11" (text-micro) ~36px. A
 *  tier is drawn only when its SHORTEST pitch clears its label, so no two labels overlap. */
export const ROADMAP_AXIS_LABEL_PX = { month: 62, quarter: 58, year: 40, week: 42 } as const;
/** The shortest pitch of each tier, in days (February; a 90-day quarter; a week). */
const SHORTEST_MONTH_DAYS = 28;
const SHORTEST_QUARTER_DAYS = 90;
const WEEK_DAYS = 7;
/** Month labels ("Jan 2026" on January, the month alone otherwise) — ≈2.2 px/day. */
export const ROADMAP_AXIS_MONTH_MIN_DAY_PX = ROADMAP_AXIS_LABEL_PX.month / SHORTEST_MONTH_DAYS;
/** Quarter labels ("Q3 2026") — ≈0.64 px/day. Years always fit: a year is 91px at the floor. */
export const ROADMAP_AXIS_QUARTER_MIN_DAY_PX = ROADMAP_AXIS_LABEL_PX.quarter / SHORTEST_QUARTER_DAYS;
/** Weekly labels at 6 px/day, alternate weeks at 3. */
export const ROADMAP_AXIS_WEEK_MIN_DAY_PX = ROADMAP_AXIS_LABEL_PX.week / WEEK_DAYS;
export const ROADMAP_AXIS_ALT_WEEK_MIN_DAY_PX = ROADMAP_AXIS_LABEL_PX.week / (WEEK_DAYS * 2);

export interface RoadmapAxisTiers {
  primary: RoadmapAxisTierValue;
  weeks: RoadmapWeekTierValue;
}

export function roadmapAxisTiers(dayWidth: number): RoadmapAxisTiers {
  const primary =
    dayWidth >= ROADMAP_AXIS_MONTH_MIN_DAY_PX
      ? RoadmapAxisTier.month
      : dayWidth >= ROADMAP_AXIS_QUARTER_MIN_DAY_PX
        ? RoadmapAxisTier.quarter
        : RoadmapAxisTier.year;
  const weeks =
    dayWidth >= ROADMAP_AXIS_WEEK_MIN_DAY_PX
      ? RoadmapWeekTier.all
      : dayWidth >= ROADMAP_AXIS_ALT_WEEK_MIN_DAY_PX
        ? RoadmapWeekTier.alternate
        : RoadmapWeekTier.none;
  return { primary, weeks };
}

/** The primary tier's ticks for this zoom. The model always offers an OPENING tick at day 0
 *  (the domain rarely starts on a boundary); it is drawn only when the first real tick is far
 *  enough in — in px, at THIS day width — for both labels to fit. */
export function primaryAxisTicks(
  model: { months: AxisTick[]; quarters: AxisTick[]; years: AxisTick[] },
  primary: RoadmapAxisTierValue,
  dayWidth: number,
): AxisTick[] {
  const ticks =
    primary === RoadmapAxisTier.month
      ? model.months
      : primary === RoadmapAxisTier.quarter
        ? model.quarters
        : model.years;
  const [opening, next] = ticks;
  if (opening?.opening && next && next.index * dayWidth < ROADMAP_AXIS_LABEL_PX[primary]) {
    return ticks.slice(1);
  }
  return ticks;
}

/** Clamp a day width into the zoom range. */
export function clampDayWidth(width: number): number {
  return Math.min(ROADMAP_DAY_WIDTH_MAX, Math.max(ROADMAP_DAY_WIDTH_MIN, width));
}

/** Fit (the `A` verb): the day width that puts the whole domain into `timelineWidth` px — the
 *  pane minus the label gutter — clamped to the range. A domain too long even for the floor
 *  still overflows; a tiny one stops at the maximum rather than blowing a week across the pane. */
export function fitDayWidth(timelineWidth: number, domainDays: number): number {
  if (domainDays <= 0 || timelineWidth <= 0) return ROADMAP_DAY_WIDTH;
  return clampDayWidth(timelineWidth / domainDays);
}

/** The zoom Select's label for a level that is not a preset: a percentage of the default day
 *  width reads as "how far out am I", where "2.0px" read as nothing. */
export function zoomPercentLabel(dayWidth: number): string {
  return `${Math.round((dayWidth / ROADMAP_DAY_WIDTH) * 100)}%`;
}
