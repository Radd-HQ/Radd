/**
 * Calendar-date arithmetic for the date control (RADD-1566). Dates are ISO
 * strings ("2026-11-17") and every step is in UTC: a local `Date` slides a day
 * across a DST change or west of Greenwich, and a calendar date has no zone.
 */

import { shiftIsoDay } from "./dates";

function utc(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}

function isoOf(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** A real calendar date in ISO form, or null: 2026-02-30 is not a date. */
function isoFromParts(year: number, month: number, day: number): string | null {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1 || day > 31) return null;
  const iso = `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const ms = utc(iso);
  return Number.isNaN(ms) || isoOf(ms) !== iso ? null : iso;
}

export function isIsoDate(text: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  return Boolean(match && isoFromParts(Number(match[1]), Number(match[2]), Number(match[3])));
}

/** `shiftIsoDay`, under the name the calendar's arithmetic reads by. */
export const addDays = shiftIsoDay;

/** The same day of another month, pulled back to that month's last day when it
 *  has no such day (31 Jan + 1 month = 28 or 29 Feb). */
export function addMonths(iso: string, months: number): string {
  const [year, month, day] = iso.split("-").map(Number) as [number, number, number];
  const index = year * 12 + (month - 1) + months;
  const targetYear = Math.floor(index / 12);
  const targetMonth = (index % 12) + 1;
  for (let attempt = day; attempt >= 28; attempt -= 1) {
    const found = isoFromParts(targetYear, targetMonth, attempt);
    if (found) return found;
  }
  return isoFromParts(targetYear, targetMonth, Math.min(day, 28)) ?? iso;
}

/** Monday = 0 … Sunday = 6. */
export function weekdayIndex(iso: string): number {
  return (new Date(utc(iso)).getUTCDay() + 6) % 7;
}

/** The six Monday-first weeks that show `iso`'s month: always 42 days, so the
 *  grid never changes height between months. */
export function monthGrid(iso: string): string[][] {
  const first = `${iso.slice(0, 7)}-01`;
  const start = addDays(first, -weekdayIndex(first));
  return Array.from({ length: 6 }, (_, week) =>
    Array.from({ length: 7 }, (_, day) => addDays(start, week * 7 + day)),
  );
}

export function inRange(iso: string, min?: string, max?: string): boolean {
  return (!min || iso >= min) && (!max || iso <= max);
}

export type DateOrder = "dmy" | "mdy" | "ymd";

/** The order a locale writes a numeric date in. */
export function localeDateOrder(locale?: string): DateOrder {
  const parts = new Intl.DateTimeFormat(locale, { year: "numeric", month: "numeric", day: "numeric" })
    .formatToParts(new Date(Date.UTC(2026, 10, 22)))
    .filter((part) => part.type === "day" || part.type === "month" || part.type === "year")
    .map((part) => part.type[0]);
  const order = parts.join("");
  return order === "mdy" || order === "ymd" ? order : "dmy";
}

/** Lower-cased month names, short and long, for a locale: index = month - 1. */
export function localeMonthNames(locale?: string): string[][] {
  return Array.from({ length: 12 }, (_, month) =>
    (["short", "long"] as const).map((width) =>
      new Intl.DateTimeFormat(locale, { month: width, timeZone: "UTC" })
        .format(new Date(Date.UTC(2026, month, 1)))
        .toLowerCase()
        .replace(/\.$/, ""),
    ),
  );
}

/**
 * What a person typed, as an ISO date, or null when it cannot be read.
 * Accepted: ISO (`2026-11-22`), a numeric date in the locale's order with any
 * of `/ . -` or spaces between (`22/11/2026`, `11.22.26`), and a date with the
 * month spelled (`22 Nov 2026`, `Nov 22, 2026`, `november 22 2026`). A
 * two-digit year is this century. Nothing is guessed: `13/14/2026` is null.
 */
export function parseTypedDate(text: string, order: DateOrder, months: string[][]): string | null {
  const value = text.trim().toLowerCase();
  if (!value) return null;
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(value);
  if (iso) return isoFromParts(Number(iso[1]), Number(iso[2]), Number(iso[3]));
  const century = (year: number, digits: number) => (digits <= 2 ? 2000 + year : year);

  const word = /[^\d\s.,/\-]+/.exec(value)?.[0];
  if (word) {
    if (word.length < 3) return null;
    const month = months.findIndex((names) => names.some((name) => name.startsWith(word) || word.startsWith(name)));
    const numbers = value.match(/\d+/g) ?? [];
    if (month < 0 || numbers.length !== 2) return null;
    // The year is the one that cannot be a day: four digits, or more than 31.
    const yearAt = numbers.findIndex((n) => n.length === 4 || Number(n) > 31);
    const at = yearAt >= 0 ? yearAt : 1;
    const year = numbers[at]!;
    return isoFromParts(century(Number(year), year.length), month + 1, Number(numbers[1 - at]));
  }

  const numbers = value.split(/[\s./\-]+/).filter(Boolean);
  if (numbers.length !== 3 || numbers.some((n) => !/^\d+$/.test(n))) return null;
  const [a, b, c] = numbers as [string, string, string];
  if (order === "ymd") return isoFromParts(century(Number(a), a.length), Number(b), Number(c));
  const year = century(Number(c), c.length);
  return order === "mdy" ? isoFromParts(year, Number(a), Number(b)) : isoFromParts(year, Number(b), Number(a));
}
