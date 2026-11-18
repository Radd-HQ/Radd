import { TicketReason, type WorkCategory } from "../../lib/types";
import { durationText } from "./model";
import { QuickLogField } from "./QuickLogField";
import type { Dragged, Ticket } from "./types";

/** Why a ticket is offered, in a word or two: what they last did on it when
 *  that is the newest reason, else the standing one (RADD-1572). */
export function reasonText(ticket: Ticket): string {
  const newest = ticket.reasons?.[0];
  if (newest === TicketReason.acted && ticket.activity) return ticket.activity;
  if (newest === TicketReason.logged) return "Logged on";
  if (newest === TicketReason.assigned) return "Assigned";
  return "";
}

interface TrayProps {
  title: string;
  hint: string;
  tickets: Ticket[];
  /** Issues the text box found that are not on the list (RADD-1573). */
  found?: Ticket[];
  /** The day a typed duration is logged on, in words. */
  day: string;
  filter: string;
  onFilter: (text: string) => void;
  onLog: (ticket: Ticket, seconds: number) => void;
  onDrag: (dragged: Dragged | null) => void;
  onPeek: (key: string) => void;
}

/** The tickets a person is likely to log on, above the week (RADD-1541, 1572,
 *  1573). Two ways to log from a row: type a duration and press Enter, which
 *  logs it on the chosen day, or drag the ticket onto any day for an hour. The
 *  text box narrows the list and, from two characters, also searches every
 *  issue the person can read. */
export function TicketTray(props: TrayProps) {
  const { title, hint, tickets, found = [], day, filter, onFilter } = props;
  return (
    <section
      className="min-w-0 flex-1 rounded-xl border border-subtle bg-surface p-3 shadow-lift"
      data-ticket-tray={title}
    >
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
          {title} <span className="font-normal text-fg-faint">{tickets.length || ""}</span>
        </h3>
        <input
          value={filter}
          onChange={(event) => onFilter(event.target.value)}
          placeholder="Filter, or find any issue by key or words"
          aria-label="Filter my tickets, or find any issue by key or words"
          data-ticket-filter
          className="w-72 max-w-full rounded-md border border-strong bg-base px-2 py-1 text-row text-fg outline-focus focus-visible:outline-2"
        />
        <span className="ml-auto text-meta text-fg-secondary" data-log-target-label>
          Typed time goes on <span className="font-medium text-heading">{day}</span>
        </span>
      </div>
      {tickets.length === 0 && found.length === 0 ? (
        <p className="text-meta text-fg-faint">{filter.trim() ? "No issue matches" : hint}</p>
      ) : (
        <div className="max-h-44 overflow-y-auto pr-1">
          <ul className="grid grid-cols-1 gap-1 xl:grid-cols-2">
            {tickets.map((ticket) => (
              <TicketRow key={ticket.id} ticket={ticket} {...props} />
            ))}
          </ul>
          {found.length > 0 && (
            <>
              <h4 className="mb-1 mt-2 text-meta text-fg-muted">Other issues</h4>
              <ul className="grid grid-cols-1 gap-1 xl:grid-cols-2" data-ticket-found>
                {found.map((ticket) => (
                  <TicketRow key={ticket.id} ticket={ticket} {...props} />
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}

/** One ticket: the draggable part (key, title, why it is here) and the field.
 *  The field sits OUTSIDE the draggable element — inside one, selecting its
 *  text with the mouse starts a drag instead. */
export function TicketRow({
  ticket,
  day,
  onLog,
  onDrag,
  onPeek,
  stacked = false,
}: Pick<TrayProps, "day" | "onLog" | "onPeek"> & {
  ticket: Ticket;
  onDrag?: TrayProps["onDrag"];
  /** Two lines: the title gets the row's width and the reason goes under it.
   *  For a narrow column (the My Work widget, RADD-1579). */
  stacked?: boolean;
}) {
  const off = ticket.loggable === false;
  const why = [reasonText(ticket), ticket.mySeconds ? durationText(ticket.mySeconds) : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="flex min-w-0 items-center gap-1.5" data-tray-row={ticket.key}>
      <div
        draggable={Boolean(onDrag) && !off}
        aria-disabled={off}
        data-tray-ticket={ticket.key}
        onDragStart={(event) => {
          event.dataTransfer.effectAllowed = "copy";
          event.dataTransfer.setData("text/plain", ticket.key);
          onDrag?.({ kind: "ticket", ticket });
        }}
        onDragEnd={() => onDrag?.(null)}
        className={`flex min-w-0 flex-1 gap-x-1.5 rounded-md border border-subtle bg-base px-2 py-1 text-row ${
          stacked ? "flex-wrap items-baseline" : "items-baseline"
        } ${
          off ? "cursor-not-allowed opacity-60" : onDrag ? "cursor-grab active:cursor-grabbing" : ""
        }`}
        title={
          off
            ? `${ticket.key} ${ticket.title} — time logging is switched off for this project`
            : onDrag
              ? `${ticket.key} ${ticket.title} — drag onto a day to log 1h`
              : `${ticket.key} ${ticket.title}`
        }
      >
        <button
          type="button"
          onClick={() => onPeek(ticket.key)}
          className="shrink-0 font-mono text-meta text-accent-text hover:underline cursor-pointer"
        >
          {ticket.key}
        </button>
        <span className={`min-w-0 flex-1 text-fg-secondary ${stacked ? "line-clamp-2" : "truncate"}`}>
          {ticket.title}
        </span>
        {why && (
          <span className={`text-meta text-fg-muted ${stacked ? "w-full truncate" : "shrink-0"}`} data-ticket-why>
            {why}
          </span>
        )}
      </div>
      <QuickLogField
        subject={ticket.key}
        day={day}
        disabled={off}
        onLog={(seconds) => onLog(ticket, seconds)}
      />
    </li>
  );
}

/** General time (no issue): one chip per work category — meetings, support,
 *  training — dragged onto a day like a ticket. */
export function CategoryTray({
  categories,
  onDrag,
}: {
  categories: WorkCategory[];
  onDrag: (dragged: Dragged | null) => void;
}) {
  if (categories.length === 0) return null;
  return (
    <section
      className="rounded-xl border border-subtle bg-surface p-3 shadow-lift lg:w-64"
      data-ticket-tray="General time"
    >
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        General time
      </h3>
      <ul className="flex max-h-40 flex-wrap gap-1 overflow-y-auto">
        {categories.map((category) => (
          <li
            key={category.id}
            draggable
            data-tray-category={category.name}
            onDragStart={(event) => {
              event.dataTransfer.effectAllowed = "copy";
              event.dataTransfer.setData("text/plain", category.name);
              onDrag({ kind: "category", category });
            }}
            onDragEnd={() => onDrag(null)}
            className="cursor-grab rounded-full border border-subtle bg-base px-2 py-0.5 text-meta text-fg-secondary active:cursor-grabbing"
            title={`${category.name} — drag onto a day to log 1h with no issue`}
          >
            {category.name}
          </li>
        ))}
      </ul>
    </section>
  );
}
