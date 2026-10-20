/** Cycle bands on the roadmap axis (RADD-1511): the dated cycles that overlap
 *  the domain, as day-index spans — the cycle-centric reading's time marks. */

import type { Cycle } from "@radd-plugin-ui/cycles/types";
import { daysBetween, parseDay } from "./dates";
import type { RoadmapModel } from "./rows";

export interface RoadmapCycleBand {
  id: string;
  name: string;
  /** Inclusive day indices, clamped to the domain. */
  startIndex: number;
  endIndex: number;
  startIso: string;
  endIso: string;
}

type DatedCycle = Pick<Cycle, "id" | "name" | "start_date" | "end_date">;

/** One band per dated cycle that overlaps the domain, start-ordered; drafts
 *  (no dates) and cycles wholly outside the domain draw nothing. */
export function cycleBands(cycles: readonly DatedCycle[], model: RoadmapModel): RoadmapCycleBand[] {
  const domainStart = model.domainStart;
  if (!domainStart || model.domainDays === 0) return [];
  const last = model.domainDays - 1;
  const bands: RoadmapCycleBand[] = [];
  for (const cycle of cycles) {
    if (!cycle.start_date || !cycle.end_date) continue;
    const start = daysBetween(domainStart, parseDay(cycle.start_date));
    const end = daysBetween(domainStart, parseDay(cycle.end_date));
    if (end < 0 || start > last) continue;
    bands.push({
      id: cycle.id,
      name: cycle.name,
      startIndex: Math.max(0, start),
      endIndex: Math.min(last, end),
      startIso: cycle.start_date,
      endIso: cycle.end_date,
    });
  }
  return bands.sort((a, b) => a.startIndex - b.startIndex);
}
