/** Shared scheduling vocabulary matching the platform radd.schedule engine. */
/** Shape of a scheduled rule's `schedule` (spec 69, mirror of ScheduleKind). */
export const ScheduleKind = {
  interval: "interval",
  daily: "daily",
  weekly: "weekly",
  monthly: "monthly",
  cron: "cron",
} as const;
export type ScheduleKindValue = (typeof ScheduleKind)[keyof typeof ScheduleKind];

/** interval: {minutes >= 5}; daily: {time "HH:MM"}; weekly: {time, weekdays
 * (0=Mon, non-empty)}; monthly: {time, day}; cron: {expression}. Times run on
 * the server's scheduler timezone. */
export interface ScheduleConfig {
  kind: ScheduleKindValue;
  minutes?: number | null;
  time?: string | null;
  weekdays?: number[] | null;
  /** Monthly: day of the month, clamped to the month's last day. */
  day?: number | null;
  /** Cron: a five-field expression, validated server-side. */
  expression?: string | null;
}

/** A candidate schedule preview — when a candidate schedule would run.
 * Computed on the server so the answer is the engine's own arithmetic, and
 * `error` carries the refusal the save would give (RADD-912). */
export interface SchedulePreview {
  timezone: string;
  next_runs: string[];
  error: string | null;
}

export function defaultSchedule(kind: ScheduleKindValue): ScheduleConfig {
  switch (kind) {
    case ScheduleKind.interval:
      return { kind, minutes: 60 };
    case ScheduleKind.daily:
      return { kind, time: "09:00" };
    case ScheduleKind.monthly:
      // The 1st, because "monthly" almost always means the start of the month
      // and the alternative is asking someone to pick a number before they have
      // said what they want.
      return { kind, time: "09:00", day: 1 };
    case ScheduleKind.cron:
      return { kind, expression: "0 9 * * 1" };
    default:
      return { kind, time: "09:00", weekdays: [0] };
  }
}

/** Basic form completeness only. The owning server remains authoritative for
 * validation, including cron syntax and incompatible extra fields. */
export function isScheduleValid(schedule: ScheduleConfig): boolean {
  if (schedule.kind === ScheduleKind.interval) return Number.isInteger(schedule.minutes) && (schedule.minutes ?? 0) >= 5;
  // Only a shape check — whether the expression PARSES, and whether it fires
  // more often than the floor allows, is the server's answer. A second cron
  // parser in the browser would be a second thing to be wrong.
  if (schedule.kind === ScheduleKind.cron) return Boolean(schedule.expression?.trim());
  if (!schedule.time || !/^([01]\d|2[0-3]):[0-5]\d$/.test(schedule.time)) return false;
  if (schedule.kind === ScheduleKind.monthly) {
    const day = schedule.day ?? 0;
    return Number.isInteger(day) && day >= 1 && day <= 31;
  }
  if (schedule.kind === ScheduleKind.daily) return true;
  const days = schedule.weekdays ?? [];
  return schedule.kind === ScheduleKind.weekly && days.length > 0 &&
    new Set(days).size === days.length && days.every(day => Number.isInteger(day) && day >= 0 && day <= 6);
}
