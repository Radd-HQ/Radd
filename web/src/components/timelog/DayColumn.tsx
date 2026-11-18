import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { formatIso } from "@radd/plugin-sdk";
import { api } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import type { SearchResponse, TimesheetEntry } from "../../lib/types";
import { DROP_SECONDS, DayLoad, durationText, type DayLoadValue } from "./model";
import { ticketOfHit, type Dragged, type Ticket, type WeekActions } from "./types";
import { WorklogCard } from "./WorklogCard";

const LOAD_CLASS: Record<DayLoadValue, string> = {
  [DayLoad.empty]: "text-fg-faint",
  [DayLoad.under]: "text-status-warning-ink",
  [DayLoad.ok]: "text-status-success-ink",
  [DayLoad.over]: "text-status-danger-ink",
};
const LOAD_TITLE: Record<DayLoadValue, string> = {
  [DayLoad.empty]: "Nothing logged",
  [DayLoad.under]: "Under the expected day",
  [DayLoad.ok]: "Within the expected day",
  [DayLoad.over]: "Over the expected day",
};

interface DayProps {
  day: string;
  today: boolean;
  /** This is the day a duration typed in the tray is logged on (RADD-1573). */
  target: boolean;
  onTarget: () => void;
  working: boolean;
  entries: TimesheetEntry[];
  seconds: number;
  load: DayLoadValue;
  dragged: Dragged | null;
  actions: WeekActions;
  onDrag: (dragged: Dragged | null) => void;
}

/** One day of the week (RADD-1541): its total, its worklogs, and a drop target.
 *  A ticket or a category dropped here logs an hour; a card dropped here moves,
 *  or copies with Ctrl/Alt held. The "Add" row is the same act for the keyboard. */
export function DayColumn(props: DayProps) {
  const { day, entries, seconds, load, dragged, actions, onDrag } = props;
  const [over, setOver] = useState(false);
  const [adding, setAdding] = useState(false);

  const drop = (copy: boolean) => {
    if (!dragged) return;
    if (dragged.kind === "ticket") actions.log({ ticket: dragged.ticket }, day, DROP_SECONDS);
    else if (dragged.kind === "category") actions.log({ category: dragged.category }, day, DROP_SECONDS);
    else if (copy) {
      const { entry } = dragged;
      const ticket = entry.item
        ? { id: entry.item.id, key: entry.item.key, title: entry.item.title }
        : undefined;
      const category = entry.category
        ? { id: entry.category.id, name: entry.category.name, position: 0, archived: false }
        : undefined;
      actions.log({ ticket, category }, day, entry.time_spent_seconds, entry.note);
    } else if (dragged.entry.worked_on !== day) actions.update(dragged.entry, { day });
  };

  return (
    <section
      data-day={day}
      data-day-seconds={seconds}
      data-day-load={load}
      data-day-target={props.target || undefined}
      aria-label={`${formatIso(day, { weekday: "long", month: "long", day: "numeric" })}, ${durationText(seconds)} logged`}
      onDragOver={(event) => {
        if (!dragged) return;
        event.preventDefault();
        event.dataTransfer.dropEffect =
          dragged.kind !== "entry" || event.ctrlKey || event.altKey ? "copy" : "move";
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        drop(event.ctrlKey || event.altKey || event.metaKey);
        onDrag(null);
      }}
      className={`flex min-h-[22rem] min-w-[9.5rem] flex-1 flex-col rounded-xl border bg-surface ${
        over ? "border-emphasis bg-elevated" : props.target ? "border-accent" : "border-subtle"
      } ${props.working ? "" : "opacity-80"}`}
    >
      <header className="flex items-baseline justify-between gap-2 border-b border-subtle px-2 py-1.5">
        <button
          type="button"
          onClick={props.onTarget}
          aria-pressed={props.target}
          data-day-pick
          title={
            props.target
              ? "Time typed beside a ticket is logged on this day"
              : "Log typed time on this day"
          }
          className={`whitespace-nowrap rounded text-row font-medium cursor-pointer hover:underline ${props.today ? "text-accent-text-strong" : "text-heading"}`}
        >
          {formatIso(day, { weekday: "short", month: "short", day: "numeric" })}
        </button>
        <span className={`whitespace-nowrap text-row font-medium tabular-nums ${LOAD_CLASS[load]}`} title={LOAD_TITLE[load]} data-day-total>
          {durationText(seconds)}
        </span>
      </header>
      <div className="flex flex-1 flex-col gap-1.5 p-1.5">
        {entries.map((entry) => (
          <WorklogCard key={entry.id} entry={entry} actions={actions} onDrag={onDrag} />
        ))}
        {adding ? (
          <AddRow
            onPick={(ticket) => {
              actions.log({ ticket }, day, DROP_SECONDS);
              setAdding(false);
            }}
            onClose={() => setAdding(false)}
          />
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            data-add
            className="mt-auto flex items-center justify-center gap-1 rounded-md border border-dashed border-subtle py-1 text-meta text-fg-muted hover:border-strong hover:text-fg cursor-pointer"
          >
            <Plus size={12} aria-hidden /> Add
          </button>
        )}
      </div>
    </section>
  );
}

/** Type a key or a few words, pick an issue, an hour is logged on this day. */
function AddRow({ onPick, onClose }: { onPick: (ticket: Ticket) => void; onClose: () => void }) {
  const [text, setText] = useState("");
  const query = text.trim();
  const hits = useQuery({
    queryKey: ["timelogAddSearch", query],
    queryFn: ({ signal }) =>
      api.get<SearchResponse>(ApiPath.search, { signal, query: { q: query, limit: "6" } }),
    enabled: query.length >= 2,
    staleTime: 30_000,
  });
  const results = hits.data?.results ?? [];
  return (
    <div className="mt-auto rounded-md border border-strong bg-base p-1" data-add-row>
      <input
        autoFocus
        value={text}
        placeholder="Issue key or words…"
        aria-label="Find an issue to log time on"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          if (event.key === "Enter" && results[0]) {
            onPick(ticketOfHit(results[0]));
          }
        }}
        onBlur={(event) => {
          // Leaving for one of the results below is not leaving the row.
          if (!event.currentTarget.parentElement?.contains(event.relatedTarget as Node | null)) onClose();
        }}
        className="w-full rounded bg-transparent px-1 py-0.5 text-meta text-fg outline-focus focus-visible:outline-2"
      />
      <ul>
        {results.map((hit) => (
          <li key={hit.item_id}>
            <button
              type="button"
              data-add-hit={hit.key}
              onClick={() => onPick(ticketOfHit(hit))}
              className="flex w-full min-w-0 items-baseline gap-1.5 rounded px-1 py-0.5 text-left text-meta hover:bg-elevated cursor-pointer"
            >
              <span className="shrink-0 font-mono text-accent-text">{hit.key}</span>
              <span className="truncate text-fg-secondary">{hit.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
