import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, ChevronRight, TriangleAlert } from "lucide-react";
import {
  EmptyState, Table, TBody, Td, THead, Th, formatIso, todayIso, usePluginData,
} from "@radd/plugin-sdk";
import { TimesheetPeriod, type TimesheetPeriodValue } from "../../lib/constants";
import { useCurrentUser, usePeek } from "../../lib/hooks";
import { reviewTeamsQuery, timesheetQuery } from "../../lib/queries";
import {
  daysInRange, fromISODate, periodLabel, periodRange, shiftAnchor, toISODate,
} from "../../lib/timesheet";
import type { TimesheetEntry } from "../../lib/types";
import { readUrlState, writeUrlState } from "../../lib/url-state";
import { Button } from "../Button";
import { QueryError } from "../QueryError";
import { Select } from "../Select";
import { Spinner } from "../Spinner";
import { durationText } from "./model";
import { TeamFlag, awayHours, teamRows, type TeamDay, type TeamFlagValue, type TeamRow } from "./team";

const PERIODS: { value: TimesheetPeriodValue; label: string }[] = [
  { value: TimesheetPeriod.week, label: "Week" },
  { value: TimesheetPeriod.month, label: "Month" },
];
/** The team choice that means "no roster": whoever logged time. */
const EVERYONE = "";

const hours = (seconds: number) => durationText(seconds) || "0m";

/**
 * /timesheet → Team (RADD-1574): for a team and a period, one row per person —
 * logged against expected, and a flag with its reason on logging that is not
 * believable (a week booked on one day, days nobody works, nothing at all).
 *
 * It exists for the conversation that follows: a manager reads who to ask and
 * what to ask about, opens the row for the days and entries behind it, and
 * goes to the person. The arithmetic and the wording are `team.ts`.
 */
export function TeamReport({
  everyone,
  onOpenPerson,
}: {
  /** May see the whole instance's time (`timesheet.view`); otherwise only the
   *  teams they lead are offered (RADD-1576). */
  everyone: boolean;
  onOpenPerson: (userId: string, day: string, teamId: string) => void;
}) {
  const me = useCurrentUser();
  const { open: openPeek } = usePeek();
  const url = readUrlState();
  const [period, setPeriodState] = useState<TimesheetPeriodValue>(
    url.p === TimesheetPeriod.month ? TimesheetPeriod.month : TimesheetPeriod.week,
  );
  const [anchor, setAnchorState] = useState(() => fromISODate(url.d ?? todayIso()));
  const [picked, setPicked] = useState<string | null>(url.tm ?? null);
  const [open, setOpen] = useState<string | null>(null);

  const setPeriod = (value: TimesheetPeriodValue) => {
    setPeriodState(value);
    writeUrlState({ p: value === TimesheetPeriod.week ? null : value });
  };
  const setAnchor = (value: Date) => {
    setAnchorState(value);
    writeUrlState({ d: toISODate(value) });
  };

  const teams = useQuery(reviewTeamsQuery());
  // A roster is what lets the page list someone who logged nothing, so a team
  // is the default as soon as there is one.
  const teamId = picked ?? teams.data?.[0]?.id ?? EVERYONE;
  const { start, end } = useMemo(() => periodRange(period, anchor), [period, anchor]);
  const days = useMemo(() => daysInRange(start, end), [start, end]);
  const sheet = useQuery({
    ...timesheetQuery({ start, end, teamId: teamId || undefined }),
    // A team lead's sheet is always a team's: without one it would be the
    // whole instance, which the server would narrow to themselves.
    enabled: !teams.isPending && (everyone || Boolean(teamId)),
  });
  const annotations = usePluginData("timesheetAnnotations", { start, end }, me?.id);

  const today = todayIso();
  const rows = useMemo(() => {
    const data = sheet.data;
    if (!data) return [];
    const window = { dayStartHour: data.work_day_start_hour, hoursPerDay: data.hours_per_day };
    // Leave and holidays: the hours each takes from a person's days. Several
    // on one day add up; a whole day is a whole day whatever else is on it.
    const off = new Map<string, Map<string, number>>();
    for (const note of annotations) {
      if (!note.suppressOutlier) continue;
      const from = note.start > start ? note.start : start;
      const to = note.end < end ? note.end : end;
      const hoursOff = awayHours({ from: note.awayFrom, until: note.awayUntil }, window);
      const mine = off.get(note.personId) ?? new Map<string, number>();
      for (const day of daysInRange(from, to)) mine.set(day, (mine.get(day) ?? 0) + hoursOff);
      off.set(note.personId, mine);
    }
    return teamRows(data.people ?? [], days, data.entries, off, {
      workDays: data.work_days,
      hoursPerDay: data.hours_per_day,
      dayMaxHours: data.day_max_hours,
      lowPercent: data.attention_low_percent,
      highPercent: data.attention_high_percent,
      daysPercent: data.attention_days_percent,
      dayStartHour: data.work_day_start_hour,
      today,
    });
  }, [sheet.data, annotations, days, start, end, today]);

  const flagged = rows.filter((row) => row.attention.length > 0).length;
  const judged = days.some((day) => day < today);
  const teamOptions = [
    ...(teams.data ?? []).map((team) => ({ value: team.id, label: team.name })),
    ...(everyone ? [{ value: EVERYONE, label: "Everyone who logged time" }] : []),
  ];

  return (
    <div className="flex h-full flex-col" data-team-report>
      <header className="flex flex-wrap items-center gap-3 border-b border-subtle px-6 py-3.5">
        <span className="flex items-center gap-1.5 text-row text-fg-muted">
          Team
          <Select
            value={teamId}
            onChange={(value) => {
              setPicked(value);
              setOpen(null);
              writeUrlState({ tm: value || null });
            }}
            options={teamOptions}
            size="sm"
            aria-label="Team"
          />
        </span>
        <div className="flex overflow-hidden rounded-md border border-strong">
          {PERIODS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={period === option.value}
              onClick={() => setPeriod(option.value)}
              className={`px-2.5 py-1 text-xs cursor-pointer ${
                period === option.value ? "bg-strong text-heading" : "text-fg-secondary hover:bg-elevated"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="secondary" aria-label="Previous period" data-team-previous onClick={() => setAnchor(shiftAnchor(period, anchor, -1))}>
            <ChevronLeft size={14} aria-hidden />
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setAnchor(fromISODate(today))}>
            Today
          </Button>
          <Button size="sm" variant="secondary" aria-label="Next period" onClick={() => setAnchor(shiftAnchor(period, anchor, 1))}>
            <ChevronRight size={14} aria-hidden />
          </Button>
          <span className="ml-1 text-row text-fg" data-team-period>{periodLabel(period, start, end)}</span>
        </div>
        {sheet.data && (
          <span className="ml-auto text-row text-fg-secondary" data-team-summary>
            {flagged ? (
              <>
                <span className="font-semibold text-status-warning-ink">{flagged}</span> of {rows.length} to follow up
              </>
            ) : (
              `${rows.length} ${rows.length === 1 ? "person" : "people"}, nothing to follow up`
            )}
          </span>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {!everyone && !teams.isPending && !teamId ? (
          <EmptyState message="You do not own or manage a team, so there is no team time to review." />
        ) : sheet.isPending || teams.isPending ? (
          <Spinner />
        ) : sheet.isError ? (
          <QueryError label="the team's time" error={sheet.error} />
        ) : rows.length === 0 ? (
          <EmptyState
            message={
              teamId === EVERYONE
                ? "No time was logged in this period. Pick a team to list its people whether or not they logged any."
                : "This team has no members."
            }
          />
        ) : (
          <>
            {!judged && (
              <p className="mb-3 text-row text-fg-secondary" data-team-not-judged>
                None of this period's days is over yet, so nothing is judged. Go back a period to
                review one that is complete.
              </p>
            )}
            {teamId === EVERYONE && (
              <p className="mb-3 text-row text-fg-secondary">
                Only people who logged time are listed. Pick a team to also see who logged nothing.
              </p>
            )}
            <Table>
              <THead>
                <tr>
                  <Th>Person</Th>
                  <Th className="text-right">Logged</Th>
                  <Th className="text-right">Expected</Th>
                  <Th className="text-right">Of expected</Th>
                  <Th className="text-right">Days with time</Th>
                  <Th>To follow up</Th>
                </tr>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <Fragment key={row.id}>
                    <PersonRow row={row} open={open === row.id} onToggle={() => setOpen(open === row.id ? null : row.id)} />
                    {open === row.id && (
                      <tr data-team-detail={row.id}>
                        <td colSpan={6} className="border-b border-subtle bg-surface px-4 py-3">
                          <PersonDays
                            everyone={everyone}
                            row={row}
                            entries={sheet.data.entries.filter((entry) => entry.user.id === row.id)}
                            onPeek={openPeek}
                            onOpen={() => onOpenPerson(row.id, start, teamId)}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </TBody>
            </Table>
          </>
        )}
      </div>
    </div>
  );
}

function PersonRow({ row, open, onToggle }: { row: TeamRow; open: boolean; onToggle: () => void }) {
  const off = row.attention.length > 0;
  // The figure a flag is ABOUT is the one that is marked, not the whole row.
  const has = (...flags: TeamFlagValue[]) => row.attention.some((item) => flags.includes(item.flag));
  const marked = "font-semibold text-status-warning-ink";
  return (
    <tr data-team-row={row.id} data-team-name={row.name} data-team-flags={row.attention.map((item) => item.flag).join(",")}>
      <Td>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex items-center gap-1.5 text-left font-medium text-heading hover:underline cursor-pointer"
        >
          {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
          {row.name}
        </button>
      </Td>
      <Td className="text-right tabular-nums" data-team-logged>{hours(row.loggedSeconds)}</Td>
      <Td className="text-right tabular-nums text-fg-secondary" data-team-expected>{hours(row.expectedSeconds)}</Td>
      <Td className={`text-right tabular-nums ${has(TeamFlag.nothing, TeamFlag.under, TeamFlag.over) ? marked : ""}`}>
        {row.percent === null ? "–" : `${row.percent}%`}
      </Td>
      <Td className={`text-right tabular-nums ${has(TeamFlag.nothing, TeamFlag.fewDays) ? marked : ""}`}>
        {row.workingDays ? `${row.daysLogged} of ${row.workingDays}` : "–"}
      </Td>
      <Td>
        {off ? (
          <ul className="flex flex-col gap-0.5" data-team-reasons>
            {row.attention.map((item) => (
              <li key={item.flag} className="flex items-start gap-1.5 text-status-warning-ink">
                <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0" />
                <span>{item.reason}</span>
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-fg-muted">Nothing</span>
        )}
      </Td>
    </tr>
  );
}

function dayClass(day: TeamDay): string {
  if (day.long) return "border-status-danger-ink text-status-danger-ink";
  if (day.open || day.exempt || !day.working) return "border-subtle text-fg-muted";
  if (day.seconds === 0) return "border-status-warning-ink text-status-warning-ink";
  return "border-subtle text-fg";
}

function dayTitle(day: TeamDay): string {
  if (day.exempt) return "Leave or a holiday: nothing expected";
  if (day.open) return "Not over yet: not judged";
  if (day.long) return "More than a day's maximum";
  if (!day.working) return "Not a working day";
  const part = day.partial ? `Leave for part of the day: ${hours(day.expectedSeconds)} expected` : "";
  if (day.seconds === 0) return part ? `${part}, nothing logged` : "A working day with nothing logged";
  return part;
}

/** The days behind one person's row, and the entries on them: what the
 *  manager looks at before asking. */
function PersonDays({
  row,
  entries,
  onPeek,
  onOpen,
  everyone,
}: {
  everyone: boolean;
  row: TeamRow;
  entries: TimesheetEntry[];
  onPeek: (key: string) => void;
  onOpen: () => void;
}) {
  const byDay = new Map<string, TimesheetEntry[]>();
  for (const entry of entries) byDay.set(entry.worked_on, [...(byDay.get(entry.worked_on) ?? []), entry]);
  return (
    <div className="flex flex-col gap-3">
      <ol className="flex flex-wrap gap-1" aria-label={`${row.name}, day by day`}>
        {row.days.map((day) => (
          <li
            key={day.day}
            data-team-day={day.day}
            data-team-day-expected={day.expectedSeconds}
            title={dayTitle(day) || undefined}
            className={`flex w-16 flex-col items-center rounded-md border bg-base px-1 py-1 ${dayClass(day)}`}
          >
            <span className="text-meta text-fg-muted">
              {formatIso(day.day, { weekday: "short", day: "numeric" })}
            </span>
            <span className="text-row font-medium tabular-nums">
              {day.exempt && day.seconds === 0 ? "off" : day.seconds ? hours(day.seconds) : "·"}
            </span>
            {day.partial && (
              <span className="text-meta text-fg-muted" data-team-day-part>
                of {hours(day.expectedSeconds)}
              </span>
            )}
          </li>
        ))}
      </ol>
      {entries.length === 0 ? (
        <p className="text-row text-fg-muted">No time logged in this period.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {[...byDay.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([day, list]) => (
            <li key={day} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-row">
              <span className="w-28 shrink-0 text-fg-secondary">
                {formatIso(day, { weekday: "short", month: "short", day: "numeric" })}
              </span>
              <ul className="flex min-w-0 flex-1 flex-col gap-0.5">
                {list.map((entry) => (
                  <li key={entry.id} className="flex min-w-0 items-baseline gap-2">
                    <span className="w-16 shrink-0 text-right font-medium tabular-nums text-heading">
                      {hours(entry.time_spent_seconds)}
                    </span>
                    {entry.item ? (
                      <button
                        type="button"
                        onClick={() => onPeek(entry.item!.key)}
                        className="shrink-0 font-mono text-meta text-accent-text hover:underline cursor-pointer"
                      >
                        {entry.item.key}
                      </button>
                    ) : null}
                    <span className="min-w-0 truncate text-fg-secondary">
                      {entry.item ? entry.item.title : entry.category?.name ?? "General time"}
                      {entry.note ? ` — ${entry.note}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      <div>
        <Button size="sm" variant="secondary" onClick={onOpen} data-team-open-report>
          {everyone ? `Open ${row.name}'s time in the report` : "Open the team's time in the report"}
        </Button>
      </div>
    </div>
  );
}
