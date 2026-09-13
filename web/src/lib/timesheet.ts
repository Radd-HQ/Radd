/**
 * Pure timesheet helpers (spec 22): resolve a period + anchor date into a
 * [start, end] window, enumerate the day columns, and pivot flat worklog
 * entries into grid rows grouped by issue or person. Dates are calendar days
 * handled as local Y/M/D and formatted as `YYYY-MM-DD` to match the API;
 * labels and "today" come from `lib/dates` (the reader's zone, RADD-1008).
 */

import {
  TimesheetGroupBy,
  TimesheetPeriod,
  type TimesheetGroupByValue,
  type TimesheetPeriodValue,
} from "./constants";
import type { TimesheetEntry } from "./types";
import { formatIso } from "./dates";

// TimesheetGroupByValue/TimesheetPeriodValue live in constants; re-export the
// value objects here so callers import period/grouping from one place.
export { TimesheetGroupBy, TimesheetPeriod };

export function toISODate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function fromISODate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Resolve the [start, end] window (inclusive, ISO) for a period around an anchor. */
export function periodRange(
  period: TimesheetPeriodValue,
  anchor: Date,
): { start: string; end: string } {
  if (period === TimesheetPeriod.day) {
    const iso = toISODate(anchor);
    return { start: iso, end: iso };
  }
  if (period === TimesheetPeriod.week) {
    const monday = new Date(anchor);
    // getDay(): 0=Sun..6=Sat — shift back to Monday.
    monday.setDate(anchor.getDate() - ((anchor.getDay() + 6) % 7));
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    return { start: toISODate(monday), end: toISODate(sunday) };
  }
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  return { start: toISODate(first), end: toISODate(last) };
}

/** Move the anchor one period backward (-1) or forward (+1). */
export function shiftAnchor(
  period: TimesheetPeriodValue,
  anchor: Date,
  direction: -1 | 1,
): Date {
  const next = new Date(anchor);
  if (period === TimesheetPeriod.day) next.setDate(anchor.getDate() + direction);
  else if (period === TimesheetPeriod.week) next.setDate(anchor.getDate() + 7 * direction);
  else next.setMonth(anchor.getMonth() + direction);
  return next;
}

/** Inclusive list of `YYYY-MM-DD` day columns between two ISO dates. */
export function daysInRange(startISO: string, endISO: string): string[] {
  const days: string[] = [];
  const cursor = fromISODate(startISO);
  const end = fromISODate(endISO);
  while (cursor <= end) {
    days.push(toISODate(cursor));
    cursor.setDate(cursor.getDate() + 1);
  }
  return days;
}

/** A short human label for the current window (e.g. "Jul 13 – 19, 2026"). */
export function periodLabel(
  period: TimesheetPeriodValue,
  startISO: string,
  endISO: string,
): string {
  if (period === TimesheetPeriod.day) return formatIso(startISO, { dateStyle: "full" });
  if (period === TimesheetPeriod.month) return formatIso(startISO, { month: "long", year: "numeric" });
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  return `${formatIso(startISO, opts)} – ${formatIso(endISO, { ...opts, year: "numeric" })}`;
}

export interface TimesheetRow {
  key: string;
  label: string;
  sublabel?: string;
  /** itemKey when grouping by issue — for the row's link. */
  itemKey?: string;
  /** True for a category-identity row (itemless bucket or category grouping). */
  isCategory?: boolean;
  byDay: Record<string, number>;
  total: number;
  entries: TimesheetEntry[];
}

/** Label for an entry's category, with the item-log fallback bucket. */
export const UNCATEGORIZED = "Uncategorized";

function categoryName(entry: TimesheetEntry): string {
  return entry.category?.name ?? UNCATEGORIZED;
}

/** Row identity per grouping (spec 59): itemless entries group by their CATEGORY
 * in the issue view — "Meetings" is a first-class row beside the issue keys. */
function rowSeed(
  entry: TimesheetEntry,
  groupBy: TimesheetGroupByValue,
): Omit<TimesheetRow, "byDay" | "total" | "entries"> {
  if (groupBy === TimesheetGroupBy.person) {
    return { key: entry.user.id, label: entry.user.name };
  }
  if (groupBy === TimesheetGroupBy.category) {
    return {
      key: `cat:${entry.category?.id ?? "none"}`,
      label: categoryName(entry),
      isCategory: true,
    };
  }
  if (groupBy === TimesheetGroupBy.epic) {
    // No epic is a real bucket, not an error: general worklogs have no issue at
    // all, and plenty of issues legitimately sit outside an epic. Collapsing
    // both into one row would hide how much time never rolls up.
    if (!entry.epic) {
      return { key: "epic:none", label: "No epic", sublabel: "Not under an epic" };
    }
    return {
      key: entry.epic.id,
      label: entry.epic.key,
      sublabel: entry.epic.title,
      itemKey: entry.epic.key,
    };
  }
  if (entry.item) {
    return {
      key: entry.item.id,
      label: entry.item.key,
      sublabel: entry.item.title,
      itemKey: entry.item.key,
    };
  }
  return {
    key: `cat:${entry.category?.id ?? "none"}`,
    label: categoryName(entry),
    sublabel: entry.project_key ? `${entry.project_key} · no issue` : "no issue",
    isCategory: true,
  };
}

/** Pivot entries into rows grouped by issue, person, or category — per-day sums. */
export function pivotRows(
  entries: TimesheetEntry[],
  groupBy: TimesheetGroupByValue,
): TimesheetRow[] {
  const rows = new Map<string, TimesheetRow>();
  for (const entry of entries) {
    const seed = rowSeed(entry, groupBy);
    let row = rows.get(seed.key);
    if (!row) {
      row = { ...seed, byDay: {}, total: 0, entries: [] };
      rows.set(seed.key, row);
    }
    row.byDay[entry.worked_on] = (row.byDay[entry.worked_on] ?? 0) + entry.time_spent_seconds;
    row.total += entry.time_spent_seconds;
    row.entries.push(entry);
  }
  return [...rows.values()].sort((a, b) => b.total - a.total);
}

/** Per-category totals for the summary strip — categories as first-class facts
 * of the filtered window, whatever the grid grouping. */
export function categoryTotals(
  entries: TimesheetEntry[],
): { name: string; seconds: number }[] {
  const totals = new Map<string, number>();
  for (const entry of entries) {
    const name = categoryName(entry);
    totals.set(name, (totals.get(name) ?? 0) + entry.time_spent_seconds);
  }
  return [...totals.entries()]
    .map(([name, seconds]) => ({ name, seconds }))
    .sort((a, b) => b.seconds - a.seconds);
}
