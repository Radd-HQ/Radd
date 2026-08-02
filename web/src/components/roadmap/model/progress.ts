/** Roadmap progress tints: the fraction of a bar's width to overlay (in-bar band + hover card). */

import type {
  ItemRollup,
  ItemTimelogBatchEntry,
  RollupResponse,
  TimelogBatchResponse,
} from "../../../lib/types";
import { RoadmapRowKind, type RoadmapRow } from "./rows";

// ---------------------------------------------------------------------------
// Progress tints (bar-presentation polish): the fraction of a
// bar's width to overlay — the SAME numbers feed the in-bar band and the
// hover card, so the two can never disagree.
// ---------------------------------------------------------------------------

/** A bar's progress overlay geometry. */
export interface BarProgress {
  /** Fraction of the bar width to tint, clamped to [0, 1]. */
  fraction: number;
  /** Leaves only: logged exceeds the estimate — full band + red right edge. */
  overlogged: boolean;
}

/** Leaf progress = logged/estimate off the spec-78 timelog batch. No
 *  estimate (null/0/absent entry) → null → no tint. */
export function leafBarProgress(entry: ItemTimelogBatchEntry | undefined): BarProgress | null {
  if (!entry?.estimate_seconds || entry.estimate_seconds <= 0) return null;
  const ratio = entry.logged_seconds / entry.estimate_seconds;
  return { fraction: Math.min(Math.max(ratio, 0), 1), overlogged: ratio > 1 };
}

/** Epic progress = done/total children off the spec-76 rollup batch. No
 *  descendants (total 0/absent entry) → null → no tint. */
export function epicBarProgress(rollup: ItemRollup | undefined): BarProgress | null {
  if (!rollup || rollup.total <= 0) return null;
  return { fraction: Math.min(rollup.done / rollup.total, 1), overlogged: false };
}

/** The progress for one row: epics read the rollup map, leaves the timelog
 *  map. Either map absent (fetch pending/failed/disabled) → quiet null. */
export function rowBarProgress(
  row: RoadmapRow,
  timelogByItem: TimelogBatchResponse | undefined,
  rollupByItem: RollupResponse | undefined,
): BarProgress | null {
  return row.rowKind === RoadmapRowKind.epic
    ? epicBarProgress(rollupByItem?.[row.item.id])
    : leafBarProgress(timelogByItem?.[row.item.id]);
}
