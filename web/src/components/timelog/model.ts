/**
 * The time-entry calendar's arithmetic (RADD-1541): a week of days, a person's
 * worklogs grouped under them, and the snapping a drag or a resize does.
 * Pure — the components hold the state, this decides what a gesture means.
 */

/** Durations move in quarter hours: the smallest slice anyone books. */
export const STEP_SECONDS = 15 * 60;
/** What a ticket dropped on a day logs — the reference tool's gesture. */
export const DROP_SECONDS = 60 * 60;
/** Card height per logged hour, and the floor that keeps a 15-minute card legible. */
export const HOUR_PX = 44;
export const MIN_CARD_PX = 58;

const DAY_MS = 86_400_000;

function utc(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}

function isoOf(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** The Monday of `iso`'s week. Date-only arithmetic in UTC: a local Date here
 *  slides a day across a DST change or west of Greenwich. */
export function weekStart(iso: string): string {
  const ms = utc(iso);
  const weekday = (new Date(ms).getUTCDay() + 6) % 7; // Monday = 0
  return isoOf(ms - weekday * DAY_MS);
}

/** The seven days from `start`. */
export function weekDays(start: string): string[] {
  return Array.from({ length: 7 }, (_, index) => isoOf(utc(start) + index * DAY_MS));
}

export function shiftWeek(start: string, weeks: number): string {
  return isoOf(utc(start) + weeks * 7 * DAY_MS);
}

/** Round to the nearest quarter hour, never below one. */
export function snapSeconds(seconds: number): number {
  return Math.max(STEP_SECONDS, Math.round(seconds / STEP_SECONDS) * STEP_SECONDS);
}

/** The duration a card resized by `deltaPx` ends at. */
export function resizedSeconds(seconds: number, deltaPx: number): number {
  return snapSeconds(seconds + (deltaPx / HOUR_PX) * 3600);
}

export function cardHeight(seconds: number): number {
  return Math.max(MIN_CARD_PX, Math.round((seconds / 3600) * HOUR_PX));
}

/** Duration text the server parses (`1h 30m`). Hours and minutes only: the
 *  server's `d` and `w` depend on the instance's working day, a quarter-hour
 *  figure does not. */
export function durationText(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours && rest) return `${hours}h ${rest}m`;
  return hours ? `${hours}h` : `${rest}m`;
}

/** `1h 30m`, `90m`, `1.5h`, `1:30` or a bare number of hours → seconds, snapped
 *  to nothing: what a person typed is what they meant. Null when unreadable. */
export function parseDuration(text: string): number | null {
  const value = text.trim().toLowerCase();
  const clock = /^(\d+):([0-5]\d)$/.exec(value);
  if (clock) return Number(clock[1]) * 3600 + Number(clock[2]) * 60;
  if (/^\d+(\.\d+)?$/.test(value)) return Math.round(Number(value) * 3600);
  let seconds = 0;
  let matched = false;
  for (const [, amount, unit] of value.matchAll(/(\d+(?:\.\d+)?)\s*(h|m)/g)) {
    seconds += Number(amount) * (unit === "h" ? 3600 : 60);
    matched = true;
  }
  if (!matched || value.replace(/(\d+(?:\.\d+)?)\s*(h|m)/g, "").trim()) return null;
  return seconds > 0 ? Math.round(seconds) : null;
}

export interface DayLike {
  worked_on: string;
  time_spent_seconds: number;
}

/** Entries per day (insertion order kept) and each day's total. */
export function byDay<T extends DayLike>(
  days: string[],
  entries: T[],
): Map<string, { entries: T[]; seconds: number }> {
  const grouped = new Map(days.map((day) => [day, { entries: [] as T[], seconds: 0 }]));
  for (const entry of entries) {
    const bucket = grouped.get(entry.worked_on);
    if (!bucket) continue;
    bucket.entries.push(entry);
    bucket.seconds += entry.time_spent_seconds;
  }
  return grouped;
}

export const DayLoad = { empty: "empty", under: "under", ok: "ok", over: "over" } as const;
export type DayLoadValue = (typeof DayLoad)[keyof typeof DayLoad];

/** How a day's total reads against the instance's expected day. Only a WORKING
 *  day in the past can be under: today is still being worked, and a weekend
 *  owes nothing. */
export function dayLoad(
  seconds: number,
  opts: { minHours: number; maxHours: number; working: boolean; past: boolean },
): DayLoadValue {
  if (seconds > opts.maxHours * 3600) return DayLoad.over;
  if (seconds === 0) return opts.working && opts.past ? DayLoad.under : DayLoad.empty;
  if (seconds < opts.minHours * 3600 && opts.working && opts.past) return DayLoad.under;
  return DayLoad.ok;
}

const WEEKDAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

export function isWorkingDay(iso: string, workDays: string[]): boolean {
  return workDays.includes(WEEKDAY_NAMES[new Date(utc(iso)).getUTCDay()]!);
}
