import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { ErrorText, errorMessage, formatIso, todayIso } from "@radd/plugin-sdk";
import { api } from "../../lib/api";
import { useCurrentUser, usePeek } from "../../lib/hooks";
import { myTicketsQuery, timesheetQuery, workCategoriesQuery } from "../../lib/queries";
import { pushToast } from "../../lib/toast";
import type { Timesheet, TimesheetEntry } from "../../lib/types";
import { Button } from "../Button";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";
import { DayColumn } from "./DayColumn";
import { byDay, dayLoad, durationText, isWorkingDay, shiftWeek, weekDays, weekStart } from "./model";
import { CategoryTray, TicketTray } from "./TicketTray";
import type { Dragged, Ticket, WeekActions } from "./types";

/**
 * A person's week of time, entered where it is read (RADD-1541).
 *
 * The timesheet is a REPORT — rows across people, pivoted and drilled into — and
 * logging meant opening each issue's time panel. Pilot feedback was that this is
 * harder than the tool it replaces. This is the entry surface: one person, one
 * week, every worklog a card that is dragged, stretched, typed over or deleted
 * in place, under a daily total. It stores nothing new: each gesture is one call
 * to the worklog API the issue panel already uses.
 */
export function TimeLogCalendar({ anchor, onAnchor }: { anchor: string; onAnchor: (iso: string) => void }) {
  const me = useCurrentUser();
  const client = useQueryClient();
  const { open: openPeek } = usePeek();
  const [dragged, setDragged] = useState<Dragged | null>(null);
  const [filter, setFilter] = useState("");

  const start = weekStart(anchor);
  const days = useMemo(() => weekDays(start), [start]);
  const weekParams = { start, end: days[6]!, userId: me?.id };
  const week = useQuery({ ...timesheetQuery(weekParams), enabled: Boolean(me) });
  /** One server-ranked list: assigned, booked on lately, acted on lately (RADD-1572). */
  const mine = useQuery(myTicketsQuery());
  const categories = useQuery(workCategoriesQuery());

  const tickets = useMemo<Ticket[]>(
    () =>
      (mine.data ?? []).map((ticket) => ({
        id: ticket.id,
        key: ticket.key,
        title: ticket.title,
        loggable: ticket.loggable,
        reasons: ticket.reasons,
        activity: ticket.activity,
        mySeconds: ticket.my_seconds,
      })),
    [mine.data],
  );
  const matches = (ticket: Ticket) => {
    const needle = filter.trim().toLowerCase();
    return !needle || `${ticket.key} ${ticket.title}`.toLowerCase().includes(needle);
  };

  const settle = () => client.invalidateQueries({ queryKey: ["timesheet"] });
  /** The week on screen changes at once; the request confirms or undoes it. */
  const optimistic = (change: (entries: TimesheetEntry[]) => TimesheetEntry[]) => {
    const key = timesheetQuery(weekParams).queryKey;
    const before = client.getQueryData<Timesheet>(key);
    if (before) client.setQueryData<Timesheet>(key, { ...before, entries: change(before.entries) });
    return () => client.setQueryData(key, before);
  };
  const run = useMutation({
    mutationFn: (call: { send: () => Promise<unknown>; undo?: () => void }) => call.send(),
    onError: (error, call) => {
      call.undo?.();
      pushToast(errorMessage(error));
    },
    onSettled: settle,
  });

  const actions: WeekActions = {
    peek: openPeek,
    log: ({ ticket, category }, day, seconds, note = "") => {
      const body = { time_spent: durationText(seconds), worked_on: day, note };
      if (ticket) {
        run.mutate({
          send: () =>
            api.post(`/items/${ticket.id}/worklogs`, { ...body, category_id: category?.id }),
        });
      } else if (category) {
        run.mutate({ send: () => api.post("/worklogs", { ...body, category_id: category.id }) });
      }
    },
    update: (entry, patch) => {
      const undo = optimistic((entries) =>
        entries.map((row) =>
          row.id === entry.id
            ? {
                ...row,
                worked_on: patch.day ?? row.worked_on,
                time_spent_seconds: patch.seconds ?? row.time_spent_seconds,
                note: patch.note ?? row.note,
              }
            : row,
        ),
      );
      run.mutate({
        undo,
        send: () =>
          api.patch(`/worklogs/${entry.id}`, {
            worked_on: patch.day,
            time_spent: patch.seconds === undefined ? undefined : durationText(patch.seconds),
            note: patch.note,
          }),
      });
    },
    remove: (entry) => {
      const undo = optimistic((entries) => entries.filter((row) => row.id !== entry.id));
      run.mutate({ undo, send: () => api.delete(`/worklogs/${entry.id}`) });
    },
  };

  if (!me || week.isPending) return <Spinner />;
  if (week.isError) return <QueryError label="your time" error={week.error} />;

  const sheet = week.data;
  const mineOnly = sheet.entries.filter((entry) => entry.user.id === me.id);
  const grouped = byDay(days, mineOnly);
  const today = todayIso();
  const total = mineOnly.reduce((sum, entry) => sum + entry.time_spent_seconds, 0);

  return (
    <div className="flex flex-col gap-3" data-timelog-calendar>
      <div className="flex flex-col gap-3 lg:flex-row">
        <TicketTray
          title="My tickets"
          hint={mine.isPending ? "Loading…" : "Issues assigned to you, or that you logged time on or worked on lately, show up here"}
          tickets={tickets.filter(matches)}
          onDrag={setDragged}
          onPeek={openPeek}
        />
        <CategoryTray
          categories={(categories.data ?? []).filter((category) => !category.archived)}
          onDrag={setDragged}
        />
      </div>
      {mine.isError && <ErrorText error={mine.error} />}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" aria-label="Previous week" onClick={() => onAnchor(shiftWeek(start, -1))}>
          <ChevronLeft size={14} aria-hidden />
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onAnchor(today)}>
          Today
        </Button>
        <Button size="sm" variant="secondary" aria-label="Next week" onClick={() => onAnchor(shiftWeek(start, 1))}>
          <ChevronRight size={14} aria-hidden />
        </Button>
        <h2 className="text-base font-semibold text-heading" data-week-label>
          {formatIso(start, { month: "short", day: "numeric" })} –{" "}
          {formatIso(days[6]!, { month: "short", day: "numeric", year: "numeric" })}
        </h2>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter tickets by key or title"
          aria-label="Filter tickets by key or title"
          className="w-56 rounded-md border border-strong bg-base px-2 py-1 text-row text-fg outline-focus focus-visible:outline-2"
        />
        <span className="ml-auto text-row text-fg-secondary" data-week-total>
          Week total: <span className="font-semibold tabular-nums text-heading">{durationText(total)}</span>
        </span>
      </div>
      <p className="text-meta text-fg-muted">
        Drag a ticket onto a day to log an hour. Drag a card to another day to move it, with Ctrl or
        Alt held to copy it. Pull a card's bottom edge to change its duration, or double-click the
        duration to type one; double-click the card for a note. With a card focused: + and − change
        it by 15 minutes, Enter edits the duration, N the note, Delete removes it.
      </p>

      <div className="flex gap-2 overflow-x-auto pb-2" role="group" aria-label="Week">
        {days.map((day) => {
          const bucket = grouped.get(day)!;
          const working = isWorkingDay(day, sheet.work_days ?? []);
          return (
            <DayColumn
              key={day}
              day={day}
              today={day === today}
              working={working}
              entries={bucket.entries}
              seconds={bucket.seconds}
              load={dayLoad(bucket.seconds, {
                minHours: sheet.day_min_hours ?? 6,
                maxHours: sheet.day_max_hours ?? 10,
                working,
                past: day < today,
              })}
              dragged={dragged}
              actions={actions}
              onDrag={setDragged}
            />
          );
        })}
      </div>
    </div>
  );
}
