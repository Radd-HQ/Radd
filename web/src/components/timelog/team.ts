/**
 * The timesheet's Team view (RADD-1574): for each person over a period, what
 * they logged against what their working days expect, and whether the way they
 * logged it is believable.
 *
 * The flags exist so a manager can ask a person about a specific thing, so each
 * one carries its reason in words with the figures in it. Pure: the component
 * fetches, this decides.
 *
 * Only COMPLETED days are judged. A day still being worked always reads short,
 * and a period that has only just begun would flag everyone.
 *
 * Leave lowers what a day expects by the hours it takes from the working
 * window (RADD-1577): a whole day off expects nothing, a half day expects half.
 */
import { durationText, isWorkingDay } from "./model";

export const TeamFlag = {
  /** A period with working days in it and no time at all. */
  nothing: "nothing",
  /** Well under what the working days expect. */
  under: "under",
  /** Well over it. */
  over: "over",
  /** The time sits on too few of the days: booked in one go, not as it happened. */
  fewDays: "few_days",
  /** A single day holds more than the daily maximum. */
  longDay: "long_day",
} as const;
export type TeamFlagValue = (typeof TeamFlag)[keyof typeof TeamFlag];

export interface TeamEntry {
  user: { id: string; name: string };
  worked_on: string;
  time_spent_seconds: number;
}

export interface TeamRules {
  /** Working days of the week, "mon".."sun". */
  workDays: string[];
  /** What one working day expects, in hours. */
  hoursPerDay: number;
  /** A day over this many hours is not believable. */
  dayMaxHours: number;
  /** Under / over this percent of expected draws attention. */
  lowPercent: number;
  highPercent: number;
  /** Time on fewer than this percent of the working days draws attention. */
  daysPercent: number;
  /** The hour the working day starts: with `hoursPerDay`, the window part-day
   *  leave is subtracted from. */
  dayStartHour: number;
  /** Today, as an ISO date: days from here on are not judged yet. */
  today: string;
}

export interface TeamDay {
  day: string;
  seconds: number;
  working: boolean;
  /** What the day expects: a working day's hours, less any leave on it. */
  expectedSeconds: number;
  /** Leave or a holiday covers the working day: nothing is expected of it. */
  exempt: boolean;
  /** Leave covers part of it (RADD-1577): less is expected, not nothing. */
  partial: boolean;
  /** Not over yet (today or later): shown, never judged. */
  open: boolean;
  long: boolean;
}

export interface TeamAttention {
  flag: TeamFlagValue;
  /** The thing to ask about, with its figures. */
  reason: string;
}

export interface TeamRow {
  id: string;
  name: string;
  /** Logged on completed days / expected of them, in seconds. */
  loggedSeconds: number;
  expectedSeconds: number;
  /** Null when nothing was expected (all leave, or no completed working day). */
  percent: number | null;
  /** Working days judged, and how many of them carry any time. */
  workingDays: number;
  daysLogged: number;
  days: TeamDay[];
  attention: TeamAttention[];
}

const hours = (seconds: number) => durationText(seconds) || "0m";

function dayName(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

/** A time away on one day, "HH:MM" wall clock; an absent bound is that end of the day. */
export interface Away {
  from?: string;
  until?: string;
}

/** Hours off per day; `WHOLE_DAY` when nothing is expected of it at all. */
export type TimeOff = ReadonlyMap<string, number>;
export const WHOLE_DAY = Number.POSITIVE_INFINITY;

const minutes = (clock: string): number => {
  const [hour, minute] = clock.split(":").map(Number);
  return (hour || 0) * 60 + (minute || 0);
};

/**
 * How many of a working day's hours a time away takes (RADD-1577): its overlap
 * with the window the day's hours are expected in. A whole-day absence, or one
 * that covers the window, is `WHOLE_DAY`.
 */
export function awayHours(away: Away, rules: Pick<TeamRules, "dayStartHour" | "hoursPerDay">): number {
  if (!away.from && !away.until) return WHOLE_DAY;
  const opens = rules.dayStartHour * 60;
  const closes = opens + rules.hoursPerDay * 60;
  const from = Math.max(opens, away.from ? minutes(away.from) : 0);
  const until = Math.min(closes, away.until ? minutes(away.until) : 24 * 60);
  const off = Math.max(0, until - from) / 60;
  return off >= rules.hoursPerDay ? WHOLE_DAY : off;
}

/** One person's period. `off` is the hours leave or a holiday takes from each day. */
export function teamRow(
  person: { id: string; name: string },
  days: string[],
  entries: TeamEntry[],
  off: TimeOff,
  rules: TeamRules,
): TeamRow {
  const perDay = new Map<string, number>();
  for (const entry of entries) {
    if (entry.user.id !== person.id) continue;
    perDay.set(entry.worked_on, (perDay.get(entry.worked_on) ?? 0) + entry.time_spent_seconds);
  }
  const maxSeconds = rules.dayMaxHours * 3600;
  const breakdown: TeamDay[] = days.map((day) => {
    const seconds = perDay.get(day) ?? 0;
    const open = day >= rules.today;
    const working = isWorkingDay(day, rules.workDays);
    const away = Math.min(off.get(day) ?? 0, rules.hoursPerDay);
    return {
      day,
      seconds,
      working,
      expectedSeconds: working ? Math.round((rules.hoursPerDay - away) * 3600) : 0,
      exempt: away >= rules.hoursPerDay,
      partial: working && away > 0 && away < rules.hoursPerDay,
      open,
      long: !open && seconds > maxSeconds,
    };
  });

  const judged = breakdown.filter((day) => !day.open);
  const expectedOf = judged.filter((day) => day.working && !day.exempt);
  const loggedSeconds = judged.reduce((sum, day) => sum + day.seconds, 0);
  const expectedSeconds = expectedOf.reduce((sum, day) => sum + day.expectedSeconds, 0);
  const daysLogged = expectedOf.filter((day) => day.seconds > 0).length;
  const percent = expectedSeconds ? Math.round((loggedSeconds / expectedSeconds) * 100) : null;

  const attention: TeamAttention[] = [];
  const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;
  if (expectedSeconds > 0 && loggedSeconds === 0) {
    attention.push({
      flag: TeamFlag.nothing,
      reason: `Nothing logged in ${count(expectedOf.length, "working day")}`,
    });
  } else if (percent !== null) {
    if (percent < rules.lowPercent) {
      attention.push({
        flag: TeamFlag.under,
        reason: `${hours(loggedSeconds)} logged of ${hours(expectedSeconds)} expected (${percent}%)`,
      });
    } else if (percent > rules.highPercent) {
      attention.push({
        flag: TeamFlag.over,
        reason: `${hours(loggedSeconds)} logged against ${hours(expectedSeconds)} expected (${percent}%)`,
      });
    }
    // Booked in one go. Not judged on a single working day: one day of one is all of them.
    if (
      expectedOf.length > 1 &&
      loggedSeconds > 0 &&
      (daysLogged / expectedOf.length) * 100 < rules.daysPercent
    ) {
      const biggest = judged.reduce((top, day) => (day.seconds > top.seconds ? day : top));
      attention.push({
        flag: TeamFlag.fewDays,
        reason: `Time on ${daysLogged} of ${count(expectedOf.length, "working day")}; ${hours(biggest.seconds)} of it on ${dayName(biggest.day)}`,
      });
    }
  }
  const long = judged.filter((day) => day.long);
  if (long.length) {
    attention.push({
      flag: TeamFlag.longDay,
      reason: `${count(long.length, "day")} over ${rules.dayMaxHours}h: ${long
        .map((day) => `${dayName(day.day)} (${hours(day.seconds)})`)
        .join(", ")}`,
    });
  }

  return {
    id: person.id,
    name: person.name,
    loggedSeconds,
    expectedSeconds,
    percent,
    workingDays: expectedOf.length,
    daysLogged,
    days: breakdown,
    attention,
  };
}

/** How far a row is from what was expected: what sorts the worst first. */
function distance(row: TeamRow): number {
  return row.percent === null ? 0 : Math.abs(row.percent - 100);
}

/**
 * Every person the sheet covers, flagged people first and the furthest from
 * expected first among them. `people` is the roster; anyone who logged time
 * but is not on it (an "everyone" sheet has no roster) is added from the
 * entries, so no hours are dropped.
 */
export function teamRows(
  people: { id: string; name: string }[],
  days: string[],
  entries: TeamEntry[],
  off: ReadonlyMap<string, TimeOff>,
  rules: TeamRules,
): TeamRow[] {
  const roster = new Map(people.map((person) => [person.id, person]));
  for (const entry of entries) if (!roster.has(entry.user.id)) roster.set(entry.user.id, entry.user);
  const none: TimeOff = new Map();
  return [...roster.values()]
    .map((person) => teamRow(person, days, entries, off.get(person.id) ?? none, rules))
    .sort(
      (a, b) =>
        Number(b.attention.length > 0) - Number(a.attention.length > 0) ||
        b.attention.length - a.attention.length ||
        distance(b) - distance(a) ||
        a.name.localeCompare(b.name),
    );
}
