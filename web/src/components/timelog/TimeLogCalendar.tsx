import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { ErrorText, errorMessage, formatIso, todayIso } from "@radd/plugin-sdk";
import { api } from "../../lib/api";
import { useCurrentUser, usePeek } from "../../lib/hooks";
import { timesheetQuery, workCategoriesQuery } from "../../lib/queries";
import { pushToast } from "../../lib/toast";
import type { Item, Timesheet, TimesheetEntry } from "../../lib/types";
import { Button } from "../Button";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";
import { DayColumn } from "./DayColumn";
import { byDay, dayLoad, durationText, isWorkingDay, shiftWeek, weekDays, weekStart } from "./model";
import { CategoryTray, TicketTray } from "./TicketTray";
import type { Dragged, Ticket, WeekActions } from "./types";

/** How far back "Recently logged" looks, and how many it offers. */
const RECENT_WEEKS = 4;
const RECENT_MAX = 16;
const ASSIGNED_SLQ =
  "assignee = me AND category != done AND category != canceled ORDER BY updated DESC";

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
  const recent = useQuery({
    ...timesheetQuery({ start: shiftWeek(start, -RECENT_WEEKS), end: days[6]!, userId: me?.id }),
    enabled: Boolean(me),
    staleTime: 60_000,
  });
  const assigned = useQuery({
    queryKey: ["timelogAssigned"],
    queryFn: ({ signal }) =>
      api.get<Item[]>("/items", { signal, query: { q: ASSIGNED_SLQ, limit: "60" } }),
    staleTime: 60_000,
  });
  const categories = useQuery(workCategoriesQuery());
  /** Projects that take time at all: asked once, so a ticket that cannot be
   *  logged against says so in the tray instead of refusing the drop. */
  const loggable = useQuery({
    queryKey: ["timelogLoggableProjects"],
    queryFn: ({ signal }) => api.get<string[]>("/timesheet/loggable-projects", { signal }),
    staleTime: 60_000,
  });

  const matches = (ticket: Ticket) => {
    const needle = filter.trim().toLowerCase();
    return !needle || `${ticket.key} ${ticket.title}`.toLowerCase().includes(needle);
  };
  const assignedTickets = useMemo(
    () =>
      (assigned.data ?? []).map((item) => ({
        id: item.id,
        key: item.key,
        title: item.title,
        // Unknown until the list answers: assume it can, and let the server say otherwise.
        loggable: loggable.data ? loggable.data.includes(item.project_id) : true,
      })),
    [assigned.data, loggable.data],
  );
  /** Issues this person booked lately that are NOT assigned to them: the
   *  meeting, support and training tickets a team logs to every week. */
  const recentTickets = useMemo(() => {
    const mine = new Set(assignedTickets.map((ticket) => ticket.id));
    const seen = new Map<string, Ticket>();
    const entries = [...(recent.data?.entries ?? [])].sort((a, b) =>
      b.worked_on.localeCompare(a.worked_on),
    );
    for (const entry of entries) {
      if (!entry.item || mine.has(entry.item.id) || seen.has(entry.item.id)) continue;
      seen.set(entry.item.id, { id: entry.item.id, key: entry.item.key, title: entry.item.title });
      if (seen.size === RECENT_MAX) break;
    }
    return [...seen.values()];
  }, [recent.data, assignedTickets]);

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
        <div className="flex min-w-0 flex-1 flex-col gap-3 md:flex-row">
          <TicketTray
            title="Assigned to me"
            hint="Nothing open is assigned to you"
            tickets={assignedTickets.filter(matches)}
            onDrag={setDragged}
            onPeek={openPeek}
          />
          <TicketTray
            title="Recently logged"
            hint="Issues you log time on show up here"
            tickets={recentTickets.filter(matches)}
            onDrag={setDragged}
            onPeek={openPeek}
          />
        </div>
        <CategoryTray
          categories={(categories.data ?? []).filter((category) => !category.archived)}
          onDrag={setDragged}
        />
      </div>
      {assigned.isError && <ErrorText error={assigned.error} />}

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
