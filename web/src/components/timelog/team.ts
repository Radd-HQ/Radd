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
  /** Today, as an ISO date: days from here on are not judged yet. */
  today: string;
}

export interface TeamDay {
  day: string;
  seconds: number;
  working: boolean;
  /** Leave or a holiday: nothing is expected of it. */
  exempt: boolean;
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

/** One person's period. `exempt` is the days nothing is expected of them. */
export function teamRow(
  person: { id: string; name: string },
  days: string[],
  entries: TeamEntry[],
  exempt: ReadonlySet<string>,
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
    return {
      day,
      seconds,
      working: isWorkingDay(day, rules.workDays),
      exempt: exempt.has(day),
      open,
      long: !open && seconds > maxSeconds,
    };
  });

  const judged = breakdown.filter((day) => !day.open);
  const expectedOf = judged.filter((day) => day.working && !day.exempt);
  const loggedSeconds = judged.reduce((sum, day) => sum + day.seconds, 0);
  const expectedSeconds = expectedOf.length * rules.hoursPerDay * 3600;
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
  exempt: ReadonlyMap<string, ReadonlySet<string>>,
  rules: TeamRules,
): TeamRow[] {
  const roster = new Map(people.map((person) => [person.id, person]));
  for (const entry of entries) if (!roster.has(entry.user.id)) roster.set(entry.user.id, entry.user);
  const none: ReadonlySet<string> = new Set();
  return [...roster.values()]
    .map((person) => teamRow(person, days, entries, exempt.get(person.id) ?? none, rules))
    .sort(
      (a, b) =>
        Number(b.attention.length > 0) - Number(a.attention.length > 0) ||
        b.attention.length - a.attention.length ||
        distance(b) - distance(a) ||
        a.name.localeCompare(b.name),
    );
}
