import type { WorkCategory } from "../../lib/types";
import type { Dragged, Ticket } from "./types";

interface TrayProps {
  title: string;
  hint: string;
  tickets: Ticket[];
  onDrag: (dragged: Dragged | null) => void;
  onPeek: (key: string) => void;
}

/** One box of draggable tickets above the week (RADD-1541): drag one onto a
 *  day to log an hour on it. Also reachable without a mouse — the day's own
 *  "Add" row takes a typed key. */
export function TicketTray({ title, hint, tickets, onDrag, onPeek }: TrayProps) {
  return (
    <section
      className="min-w-0 flex-1 rounded-xl border border-subtle bg-surface p-3 shadow-lift"
      data-ticket-tray={title}
    >
      <h3 className="mb-2 flex items-baseline justify-between gap-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        {title}
        <span className="font-normal normal-case tracking-normal text-fg-faint">
          {tickets.length || ""}
        </span>
      </h3>
      {tickets.length === 0 ? (
        <p className="text-meta text-fg-faint">{hint}</p>
      ) : (
        <ul className="grid max-h-40 grid-cols-1 gap-1 overflow-y-auto pr-1 md:grid-cols-2">
          {tickets.map((ticket) => (
            <li
              key={ticket.id}
              draggable={ticket.loggable !== false}
              aria-disabled={ticket.loggable === false}
              data-tray-ticket={ticket.key}
              onDragStart={(event) => {
                event.dataTransfer.effectAllowed = "copy";
                event.dataTransfer.setData("text/plain", ticket.key);
                onDrag({ kind: "ticket", ticket });
              }}
              onDragEnd={() => onDrag(null)}
              className={`flex min-w-0 items-baseline gap-1.5 rounded-md border border-subtle bg-base px-2 py-1 text-row ${
                ticket.loggable === false ? "cursor-not-allowed opacity-60" : "cursor-grab active:cursor-grabbing"
              }`}
              title={
                ticket.loggable === false
                  ? `${ticket.key} ${ticket.title} — time logging is switched off for this project`
                  : `${ticket.key} ${ticket.title} — drag onto a day to log 1h`
              }
            >
              <button
                type="button"
                onClick={() => onPeek(ticket.key)}
                className="shrink-0 font-mono text-meta text-accent-text hover:underline cursor-pointer"
              >
                {ticket.key}
              </button>
              <span className="truncate text-fg-secondary">{ticket.title}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
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
