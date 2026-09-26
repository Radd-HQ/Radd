/**
 * Client-side duration formatting, for totals summed locally (the timesheet grid). Callers pass
 * the working day/week lengths from `useDurationConfig()`; the 8h/5d defaults (the server's) only
 * cover the moment before `GET /instance` resolves.
 */

export interface DurationConfig {
  hoursPerDay: number;
  daysPerWeek: number;
}

/** Mirrors the server-side RADD_TIMELOG_* defaults — pre-resolve fallback only. */
export const DEFAULT_DURATION_CONFIG: DurationConfig = { hoursPerDay: 8, daysPerWeek: 5 };

const SECONDS_PER_HOUR = 3600;

/** Seconds -> `"1w 2d 3h 30m"` (largest unit first); 0 -> `"0m"`. */
export function formatDuration(
  seconds: number,
  config: DurationConfig = DEFAULT_DURATION_CONFIG,
): string {
  if (seconds <= 0) return "0m";
  const day = config.hoursPerDay * SECONDS_PER_HOUR;
  const units: [string, number][] = [
    ["w", day * config.daysPerWeek],
    ["d", day],
    ["h", SECONDS_PER_HOUR],
    ["m", 60],
  ];
  const parts: string[] = [];
  let remaining = seconds;
  for (const [suffix, size] of units) {
    const count = Math.floor(remaining / size);
    remaining -= count * size;
    if (count > 0) parts.push(`${count}${suffix}`);
  }
  return parts.length > 0 ? parts.join(" ") : "0m";
}

/** Compact hours for column headers/totals, e.g. 9000 -> "2.5h".
 *  Pure hours — independent of the day/week config. */
export function formatHours(seconds: number): string {
  const hours = seconds / SECONDS_PER_HOUR;
  return `${Number.isInteger(hours) ? hours : hours.toFixed(2).replace(/\.?0+$/, "")}h`;
}

