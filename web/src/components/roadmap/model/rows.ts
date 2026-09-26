/** Roadmap row model: epic grouping, week-snapped domain, axis ticks (spec 82). */

import { toISODate } from "../../../lib/timesheet";
import { ItemKind, type Item } from "../../../lib/types";
import {
  ROADMAP_DOMAIN_PAD_DAYS,
  addDays,
  daysBetween,
  isScheduled,
  parseDay,
  startOfWeek,
} from "./dates";
import { formatIso, todayIso } from "@radd/plugin-sdk";

export const RoadmapRowKind = {
  epic: "epic",
  child: "child",
  standalone: "standalone",
} as const;
type RoadmapRowKindValue =(typeof RoadmapRowKind)[keyof typeof RoadmapRowKind];

export interface RoadmapRow {
  item: Item;
  rowKind: RoadmapRowKindValue;
  /** Inclusive day indices into the domain (0 = domainStart). */
  startIndex: number;
  endIndex: number;
  /**
   * Epic rows: true when the epic has no dates of its own and the span is
   * derived from its scheduled children — drawn dashed, not directly draggable.
   */
  derived: boolean;
  /** Child rows: the epic they belong to (parent auto-stretch + collapse). */
  parentEpicId: string | null;
  /** Epic rows: the scheduled children's date union (fit-to-children source). */
  childrenBounds: { minStart: string; maxTarget: string } | null;
  /** Epic rows: ALL loaded children, fetch order ("Auto-schedule children" input). */
  children: Item[];
  /** Epic rows: how many scheduled child rows render beneath (expand/collapse). */
  scheduledChildCount: number;
}

interface AxisTick {
  index: number;
  label: string;
}

export interface RoadmapModel {
  rows: RoadmapRow[];
  domainStart: Date | null;
  domainDays: number;
  weeks: AxisTick[];
  months: AxisTick[];
  /** Day index of today, or null when today is outside the domain. */
  todayIndex: number | null;
}

/** A row's effective window — a derived epic has no dates of its own, so it falls back to its children's union. */
export function rowWindowIso(row: RoadmapRow): { start: string | null; target: string | null } {
  return {
    start: row.item.start_date ?? row.childrenBounds?.minStart ?? null,
    target: row.item.target_date ?? row.childrenBounds?.maxTarget ?? null,
  };
}

const MONTH_SHORT =(date: Date) => formatIso(toISODate(date), { month: "short" });

function minDate(dates: Date[]): Date {
  return dates.reduce((a, b) => (a.getTime() <= b.getTime() ? a : b));
}
function maxDate(dates: Date[]): Date {
  return dates.reduce((a, b) => (a.getTime() >= b.getTime() ? a : b));
}

interface EpicGroup {
  epic: Item;
  /** Scheduled children only — these render as child rows, fetch order. */
  scheduledChildren: Item[];
  /** ALL loaded children in fetch order (auto-schedule input). */
  allChildren: Item[];
  /** Union of the epic's own window and its children's (domain sizing). */
  start: Date;
  end: Date;
  childrenBounds: { minStart: string; maxTarget: string } | null;
}

/** One top-level roadmap row in fetch order (spec 82): an epic group or a
 *  standalone scheduled leaf, interleaved exactly as encountered. */
type TopLevelEntry = { group: EpicGroup } | { leaf: Item };

const leafRow = (item: Item, indexOf: (date: Date) => number, rowKind: RoadmapRowKindValue, parentEpicId: string | null): RoadmapRow => ({
  item,
  rowKind,
  startIndex: indexOf(parseDay(item.start_date!)),
  endIndex: indexOf(parseDay(item.target_date!)),
  derived: false,
  parentEpicId,
  childrenBounds: null,
  children: [],
  scheduledChildCount: 0,
});

/** Session-only "+1 month" domain growth at either end (spec 78), additive
 *  over the built-in `ROADMAP_DOMAIN_PAD_DAYS`. */
export interface RoadmapExtension {
  extendBeforeDays: number;
  extendAfterDays: number;
}

export const NO_EXTENSION: RoadmapExtension = { extendBeforeDays: 0, extendAfterDays: 0 };

export function buildRoadmapModel(
  items: Item[],
  today: string = todayIso(),
  extension: RoadmapExtension = NO_EXTENSION,
): RoadmapModel {
  const epics = items.filter((item) => item.kind === ItemKind.epic);
  const epicIds = new Set(epics.map((epic) => epic.id));
  const childrenByEpic = new Map<string, Item[]>();
  for (const item of items) {
    const parentId = item.parent?.id;
    if (parentId && epicIds.has(parentId)) {
      const bucket = childrenByEpic.get(parentId);
      if (bucket) bucket.push(item);
      else childrenByEpic.set(parentId, [item]);
    }
  }

  // Spec 82: NO date sorts — fetch order (global manual rank by default) IS the
  // row order, so date edits move bars horizontally and never reshuffle rows.
  const groups: EpicGroup[] = [];
  const standalone: Item[] = [];
  const topLevel: TopLevelEntry[] = [];
  for (const item of items) {
    if (item.kind === ItemKind.epic) {
      // Epics with a drawable span (own dates and/or scheduled children).
      const allChildren = childrenByEpic.get(item.id) ?? [];
      const scheduledChildren = allChildren.filter(isScheduled);
      const starts: Date[] = [];
      const ends: Date[] = [];
      if (isScheduled(item)) {
        starts.push(parseDay(item.start_date!));
        ends.push(parseDay(item.target_date!));
      }
      for (const child of scheduledChildren) {
        starts.push(parseDay(child.start_date!));
        ends.push(parseDay(child.target_date!));
      }
      if (starts.length === 0) continue;
      const childrenBounds =
        scheduledChildren.length > 0
          ? {
              minStart: toISODate(minDate(scheduledChildren.map((c) => parseDay(c.start_date!)))),
              maxTarget: toISODate(maxDate(scheduledChildren.map((c) => parseDay(c.target_date!)))),
            }
          : null;
      const group: EpicGroup = {
        epic: item,
        scheduledChildren,
        allChildren,
        start: minDate(starts),
        end: maxDate(ends),
        childrenBounds,
      };
      groups.push(group);
      topLevel.push({ group });
    } else if (isScheduled(item) && !(item.parent && epicIds.has(item.parent.id))) {
      // Scheduled leaves that aren't a child of a loaded epic.
      standalone.push(item);
      topLevel.push({ leaf: item });
    }
  }

  // Domain: the union of every drawable window, snapped out to whole weeks,
  // plus ~a month of open space at BOTH ends (drag room — specs 77 + 78) and
  // any session "+1 month" extensions.
  const spanStarts = [...groups.map((g) => g.start), ...standalone.map((i) => parseDay(i.start_date!))];
  const spanEnds = [...groups.map((g) => g.end), ...standalone.map((i) => parseDay(i.target_date!))];
  if (spanStarts.length === 0) {
    return {
      rows: [],
      domainStart: null,
      domainDays: 0,
      weeks: [],
      months: [],
      todayIndex: null,
    };
  }

  const domainStart = startOfWeek(
    addDays(minDate(spanStarts), -(ROADMAP_DOMAIN_PAD_DAYS + extension.extendBeforeDays)),
  );
  const domainEnd = addDays(
    startOfWeek(maxDate(spanEnds)),
    6 + ROADMAP_DOMAIN_PAD_DAYS + extension.extendAfterDays,
  );
  const domainDays = daysBetween(domainStart, domainEnd) + 1;
  const indexOf = (date: Date) => daysBetween(domainStart, date);

  const rows: RoadmapRow[] = [];
  for (const entry of topLevel) {
    if ("leaf" in entry) {
      rows.push(leafRow(entry.leaf, indexOf, RoadmapRowKind.standalone, null));
      continue;
    }
    const group = entry.group;
    const derived = !isScheduled(group.epic);
    rows.push({
      item: group.epic,
      rowKind: RoadmapRowKind.epic,
      // A scheduled epic draws its OWN window (so "Fit to children" and the
      // auto-stretch are visible truths); a date-less epic draws the derived
      // children union.
      startIndex: indexOf(derived ? group.start : parseDay(group.epic.start_date!)),
      endIndex: indexOf(derived ? group.end : parseDay(group.epic.target_date!)),
      derived,
      parentEpicId: null,
      childrenBounds: group.childrenBounds,
      children: group.allChildren,
      scheduledChildCount: group.scheduledChildren.length,
    });
    for (const child of group.scheduledChildren) {
      rows.push(leafRow(child, indexOf, RoadmapRowKind.child, group.epic.id));
    }
  }

  const weeks: AxisTick[] = [];
  for (let day = new Date(domainStart); day <= domainEnd; day = addDays(day, 7)) {
    weeks.push({ index: indexOf(day), label: `${MONTH_SHORT(day)} ${day.getDate()}` });
  }

  const months: AxisTick[] = [];
  for (let day = new Date(domainStart); day <= domainEnd; day = addDays(day, 1)) {
    if (day.getDate() === 1) months.push({ index: indexOf(day), label: MONTH_SHORT(day) });
  }
  // Label the domain's opening month too, but only when the first month
  // boundary is far enough in that the two labels won't collide.
  if (months.length === 0 || months[0].index >= 6) {
    months.unshift({ index: 0, label: MONTH_SHORT(domainStart) });
  }

  const todayDate = parseDay(today);
  const todayIndex = todayDate >= domainStart && todayDate <= domainEnd ? indexOf(todayDate) : null;

  return { rows, domainStart, domainDays, weeks, months, todayIndex };
}
