import { browserTimeZone, readerTimeZone, shortDate } from "@radd/plugin-sdk";
import type { Period } from "./types";

/** The zone the reader sees timestamps in: the profile's, else the browser's. */
export const readerZone = (): string => readerTimeZone() || browserTimeZone();

/** "16:00:00" → "16:00" — a wall-clock time renders verbatim, never zone-shifted. */
export const hm = (value: string): string => value.slice(0, 5);

type Span = Pick<Period, "start_date" | "end_date" | "start_time" | "end_time">;

export const isTimed = (span: Span): boolean => Boolean(span.start_time || span.end_time);

/** "Sep 30 – Oct 3", "Sep 30, 12:00 – Oct 3, 16:00", "Sep 28, 16:00 – Sep 29", "Sep 30, 12:00 – 16:00". */
export function spanText(span: Span): string {
  const from = shortDate(span.start_date) + (span.start_time ? `, ${hm(span.start_time)}` : "");
  if (span.start_date === span.end_date) {
    if (!isTimed(span)) return from;
    return span.end_time ? `${from} – ${hm(span.end_time)}` : `${from} – end of day`;
  }
  return `${from} – ${shortDate(span.end_date)}${span.end_time ? `, ${hm(span.end_time)}` : ""}`;
}

/** The row's zone, when its times would mislead a reader in another one. */
export function zoneNote(period: Period): string | null {
  if (!isTimed(period) || !period.timezone) return null;
  return period.timezone === readerZone() ? null : period.timezone;
}

/** What a boundary day of a timed span says on the timesheet: "from 12:00", "until 16:00", "12:00–16:00". */
export function dayNote(span: Span, day: string): string {
  const first = day === span.start_date && span.start_time ? hm(span.start_time) : null;
  const last = day === span.end_date && span.end_time ? hm(span.end_time) : null;
  if (first && last) return `${first}–${last}`;
  if (first) return `from ${first}`;
  if (last) return `until ${last}`;
  return "";
}
