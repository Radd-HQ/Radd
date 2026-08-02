/**
 * Shared date formatting. Date-only API strings ("2026-07-06") are anchored
 * to LOCAL midnight before formatting — bare `new Date("2026-07-06")` parses
 * as UTC midnight, which renders the PREVIOUS day in negative-offset
 * timezones. Full timestamps pass through untouched.
 */

function parseAnchored(iso: string): Date {
  return new Date(iso.includes("T") ? iso : `${iso}T00:00:00`);
}

/** ISO date N days back from today ("2026-07-06") — report windows (0 = today). */
export function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
}

/** "2026-07-06" → "Jul 6" for compact chips and axis labels. */
export function shortDate(iso: string): string {
  return parseAnchored(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Full locale date, e.g. "7/6/2026". */
export function formatDate(iso: string): string {
  return parseAnchored(iso).toLocaleDateString();
}

/** Null-tolerant locale date for optional timestamps (token expiry, last use). */
export function formatDateOrNever(iso: string | null): string {
  return iso ? formatDate(iso) : "Never";
}

/** "Jul 27, 09:00" — compact absolute timestamp (scheduler next/last-run chips). */
export function shortDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Compact "3d ago" / "2mo ago" relative time; put the full timestamp in the title. */
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
