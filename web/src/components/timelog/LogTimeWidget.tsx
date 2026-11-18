import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Clock } from "lucide-react";
import { ErrorText, errorMessage, todayIso } from "@radd/plugin-sdk";
import { api } from "../../lib/api";
import { RoutePath } from "../../lib/constants";
import { useCurrentUser, usePeek } from "../../lib/hooks";
import { myTicketsQuery, timesheetQuery } from "../../lib/queries";
import { ToastKind, pushToast } from "../../lib/toast";
import { durationText } from "./model";
import { TicketRow } from "./TicketTray";
import type { Ticket } from "./types";

/** How many tickets the widget offers; the week's tray has the rest. */
const WIDGET_TICKETS = 8;

/**
 * My Work → Log time (RADD-1575): the tickets a person is likely to log on,
 * each with a duration field, so an hour is booked from the page they land on.
 * The list and the field are the calendar tray's (RADD-1572, 1573); here the
 * day is always today.
 */
export function LogTimeWidget() {
  const me = useCurrentUser();
  const client = useQueryClient();
  const { open: openPeek } = usePeek();
  const today = todayIso();
  const mine = useQuery(myTicketsQuery());
  const day = useQuery({
    ...timesheetQuery({ start: today, end: today, userId: me?.id }),
    enabled: Boolean(me),
  });
  const log = useMutation({
    mutationFn: ({ ticket, seconds }: { ticket: Ticket; seconds: number }) =>
      api.post(`/items/${ticket.id}/worklogs`, { time_spent: durationText(seconds), worked_on: today }),
    onSuccess: (_result, { ticket, seconds }) => pushToast(`Logged ${durationText(seconds)} on ${ticket.key}`, ToastKind.success),
    onError: (error) => pushToast(errorMessage(error)),
    onSettled: () => client.invalidateQueries({ queryKey: ["timesheet"] }),
  });

  const tickets: Ticket[] = (mine.data ?? []).slice(0, WIDGET_TICKETS).map((ticket) => ({
    id: ticket.id,
    key: ticket.key,
    title: ticket.title,
    loggable: ticket.loggable,
    reasons: ticket.reasons,
    activity: ticket.activity,
    mySeconds: ticket.my_seconds,
  }));
  const todaySeconds = (day.data?.entries ?? [])
    .filter((entry) => entry.user.id === me?.id)
    .reduce((sum, entry) => sum + entry.time_spent_seconds, 0);

  return (
    <section data-log-time-widget>
      <header className="mb-2 flex items-center gap-2">
        <Clock size={12} className="text-fg-muted" aria-hidden />
        <h2 className="text-meta font-semibold uppercase tracking-wide text-fg-muted">Log time</h2>
        <span className="text-meta text-fg-secondary" data-log-time-today>
          Today: <span className="font-semibold tabular-nums text-heading">{durationText(todaySeconds) || "0m"}</span>
        </span>
        <Link to={RoutePath.timesheet} className="ml-auto text-xs text-accent-text hover:text-accent-text-strong">
          Open my week →
        </Link>
      </header>
      {mine.isError ? (
        <ErrorText error={mine.error} />
      ) : tickets.length === 0 ? (
        <p className="rounded-lg border border-dashed border-subtle px-4 py-3 text-xs text-fg-faint">
          {mine.isPending
            ? "Loading…"
            : "Issues assigned to you, or that you logged time on or worked on lately, show up here."}
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {tickets.map((ticket) => (
            <TicketRow
              key={ticket.id}
              ticket={ticket}
              day="today"
              stacked
              onLog={(target, seconds) => log.mutate({ ticket: target, seconds })}
              onPeek={openPeek}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
