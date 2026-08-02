/**
 * Client-side duration formatting (spec 22). The API returns formatted strings
 * on individual worklogs/summaries, but the timesheet grid sums seconds locally,
 * so it needs to format its own totals. The working day/week lengths are NOT
 * hardcoded here: `GET /instance` reports the server's effective
 * `timelog_hours_per_day` / `timelog_days_per_week` (spec 67 instance-scope
 * settings), `useDurationConfig()` (lib/hooks.ts) reads them off the instance
 * query, and callers pass the pair in. The 8h/5d defaults only cover the brief
 * window before the instance query resolves (and mirror the server defaults).
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
