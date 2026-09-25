/**
 * Shared date formatting, in the READER's zone (RADD-1008).
 *
 * Every timestamp Radd renders goes through here, and here is the one place
 * that knows which zone to render it in: the profile's `timezone` when set
 * (`setReaderTimeZone`, fed from /auth/me), else the browser's. Before this,
 * the setting was stored and never read.
 *
 * Two shapes of API value, two rules:
 * - a TIMESTAMP ("2026-07-06T09:41:12Z") is an instant — it renders in the
 *   reader's zone, and so does "today" (`todayIso`), which is why the
 *   day-boundary helpers live here too;
 * - a DATE-ONLY string ("2026-07-06") is a calendar date with no zone. It
 *   renders verbatim in EVERY zone — anchored at UTC midnight and formatted
 *   in UTC — because a bare `new Date("2026-07-06")` parses as UTC midnight
 *   and renders the PREVIOUS day in negative-offset zones, and anchoring at
 *   local midnight would shift it again for a reader whose profile zone is
 *   not the browser's.
 */

let readerZone = "";

/** Is `zone` an IANA name this browser can format in? */
function isKnownTimeZone(zone: string): boolean {
  try {
    Intl.DateTimeFormat(undefined, { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/** The zone every timestamp renders in: "" (or an unknown name) = the browser's. */
export function setReaderTimeZone(zone: string | null | undefined): void {
  readerZone = zone && isKnownTimeZone(zone) ? zone : "";
}

export function readerTimeZone(): string {
  return readerZone;
}

/** The browser's own zone — what "" resolves to (the profile page's default label). */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

const UTC = "UTC";

function isDateOnly(iso: string): boolean {
  return !iso.includes("T");
}

/** An ISO date or timestamp, formatted with `options` under the rules above. */
export function formatIso(iso: string, options: Intl.DateTimeFormatOptions): string {
  if (isDateOnly(iso)) {
    return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { ...options, timeZone: UTC });
  }
  return new Date(iso).toLocaleString(undefined, { ...options, timeZone: readerZone || undefined });
}

/** The calendar date ("2026-07-06") an instant falls on in the reader's zone. */
export function isoDayOf(at: Date): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: readerZone || undefined,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(at);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/** Today's calendar date in the reader's zone. */
export function todayIso(): string {
  return isoDayOf(new Date());
}

/** ISO date `days` after `iso` (negative shifts backward) — calendar math, no zone. */
export function shiftIsoDay(iso: string, days: number): string {
  return new Date(new Date(`${iso}T00:00:00Z`).getTime() + days * 86_400_000).toISOString().slice(0, 10);
}

/** ISO date N days back from today ("2026-07-06") — report windows (0 = today). */
export function isoDaysAgo(days: number): string {
  return shiftIsoDay(todayIso(), -days);
}

/** "2026-07-06" → "Jul 6" for compact chips and axis labels. */
export function shortDate(iso: string): string {
  return formatIso(iso, { month: "short", day: "numeric" });
}

/** Full locale date, e.g. "7/6/2026". */
export function formatDate(iso: string): string {
  return formatIso(iso, { year: "numeric", month: "numeric", day: "numeric" });
}

/** Null-tolerant locale date for optional timestamps (token expiry, last use). */
export function formatDateOrNever(iso: string | null): string {
  return iso ? formatDate(iso) : "Never";
}

/** Full locale timestamp, e.g. "7/6/2026, 9:41:12 AM" — audit rows, last-login,
 * hover titles. The bare `new Date(x).toLocaleString()` this replaces was
 * scattered across the settings pages (RADD-901). */
export function formatDateTime(iso: string): string {
  return formatIso(iso, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** "Jul 27, 09:00" — compact absolute timestamp (scheduler next/last-run chips). */
export function shortDateTime(iso: string): string {
  return formatIso(iso, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Seconds as a compact duration ("5h 20m", "45m", "3d 2h") — board cards and
 * anywhere a logged/estimate readout needs one token. Days are 24h calendar
 * days here, NOT the timesheet's working-day unit (that formatting is server
 * business via the hours-per-day cascade). */
export function formatSeconds(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 24) return rest > 0 ? `${hours}h ${rest}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours > 0 ? `${days}d ${restHours}h` : `${days}d`;
}

/** Compact "3d ago" / "2mo ago" relative time; put the full timestamp in the title. */
export function relativeTime(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.round(months / 12)}y ago`;
}
