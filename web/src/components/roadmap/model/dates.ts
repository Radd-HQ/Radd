/** Roadmap date math: ISO day parsing/formatting, day-index conversion (no React). */

import { toISODate } from "../../../lib/timesheet";
import type { Item } from "../../../lib/types";

const DAY_MS = 86_400_000;

/** Open space kept BEYOND the outermost bars at BOTH ends (spec 78) so bars
 *  can be dragged into the past as well as the future. */
export const ROADMAP_DOMAIN_PAD_DAYS = 28;

/** Parse an ISO `YYYY-MM-DD` as local midnight (avoids UTC off-by-one). */
export function parseDay(iso: string): Date {
  return new Date(`${iso}T00:00:00`);
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

/** Whole calendar days from `from` to `to` (negative when `to` is earlier). */
export function daysBetween(from: Date, to: Date): number {
  return Math.round((to.getTime() - from.getTime()) / DAY_MS);
}

/** `daysBetween` over ISO `YYYY-MM-DD` strings (duration math for plans). */
export function isoDaysBetween(fromIso: string, toIso: string): number {
  return daysBetween(parseDay(fromIso), parseDay(toIso));
}

/** The ISO date at a day index of the domain (PATCH payloads from drag commits). */
export function isoFromDay(domainStart: Date, dayIndex: number): string {
  return toISODate(addDays(domainStart, dayIndex));
}

/** Monday on or before `date`. */
export function startOfWeek(date: Date): Date {
  return addDays(date, -((date.getDay() + 6) % 7));
}

/** An item can be drawn as a bar only if it has both endpoints. */
export function isScheduled(item: Item): boolean {
  return Boolean(item.start_date && item.target_date);
}
