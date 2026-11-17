import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { X } from "lucide-react";
import type { TimesheetEntry } from "../../lib/types";
import { MirroredBadge } from "../items/MirroredBadge";
import { STEP_SECONDS, cardHeight, durationText, parseDuration, resizedSeconds } from "./model";
import type { Dragged, WeekActions } from "./types";

interface CardProps {
  entry: TimesheetEntry;
  actions: WeekActions;
  onDrag: (dragged: Dragged | null) => void;
}

/** One worklog on the week (RADD-1541). Everything a person does to their time
 *  happens on the card itself: drag it to another day (Ctrl-drag copies), pull
 *  its bottom edge to change the duration, double-click the duration to type
 *  one, double-click the body for the note, × to delete. Each has a key too —
 *  the card is focusable — because a week of entries is a lot of dragging.
 *  A worklog mirrored from a merge request is shown and left alone. */
export function WorklogCard({ entry, actions, onDrag }: CardProps) {
  const mirrored = entry.external_source !== "";
  const [editing, setEditing] = useState<"duration" | "note" | null>(null);
  const [draft, setDraft] = useState("");
  /** While the bottom edge is held: the duration the card would end at. */
  const [resizing, setResizing] = useState<number | null>(null);
  const grab = useRef<{ y: number } | null>(null);

  const seconds = resizing ?? entry.time_spent_seconds;
  const label = entry.item ? entry.item.key : (entry.category?.name ?? "General");

  const begin = (what: "duration" | "note") => {
    if (mirrored) return;
    setDraft(what === "duration" ? durationText(entry.time_spent_seconds) : entry.note);
    setEditing(what);
  };
  const commit = () => {
    const value = draft.trim();
    if (editing === "note" && value !== entry.note) actions.update(entry, { note: value });
    if (editing === "duration" && value) {
      const typed = parseDuration(value);
      if (typed && typed !== entry.time_spent_seconds) actions.update(entry, { seconds: typed });
    }
    setEditing(null);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (editing || mirrored || event.target !== event.currentTarget) return;
    const step = (delta: number) => {
      event.preventDefault();
      actions.update(entry, {
        seconds: Math.max(STEP_SECONDS, entry.time_spent_seconds + delta),
      });
    };
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      actions.remove(entry);
    } else if (event.key === "+" || event.key === "=") step(STEP_SECONDS);
    else if (event.key === "-") step(-STEP_SECONDS);
    else if (event.key === "Enter") {
      event.preventDefault();
      begin("duration");
    } else if (event.key === "n") {
      event.preventDefault();
      begin("note");
    }
  };

  const onResizeDown = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    grab.current = { y: event.clientY };
    setResizing(entry.time_spent_seconds);
  };
  const onResizeMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!grab.current) return;
    setResizing(resizedSeconds(entry.time_spent_seconds, event.clientY - grab.current.y));
  };
  const onResizeUp = () => {
    if (!grab.current) return;
    grab.current = null;
    if (resizing !== null && resizing !== entry.time_spent_seconds) {
      actions.update(entry, { seconds: resizing });
    }
    setResizing(null);
  };

  return (
    <article
      tabIndex={0}
      draggable={!mirrored && !editing && resizing === null}
      data-worklog={entry.id}
      data-worklog-key={label}
      data-seconds={seconds}
      aria-label={`${label}, ${durationText(seconds)}${entry.note ? `, ${entry.note}` : ""}`}
      onKeyDown={onKeyDown}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "copyMove";
        event.dataTransfer.setData("text/plain", label);
        onDrag({ kind: "entry", entry });
      }}
      onDragEnd={() => onDrag(null)}
      style={{ minHeight: cardHeight(seconds) }}
      className={`group/card relative flex flex-col rounded-md border border-l-4 border-subtle bg-elevated px-2 pb-2.5 pt-1 text-row outline-focus focus-visible:outline-2 ${
        entry.item ? "border-l-accent" : "border-l-strong"
      } ${mirrored ? "opacity-90" : "cursor-grab active:cursor-grabbing"}`}
    >
      <header className="flex items-baseline gap-1.5">
        {entry.item ? (
          <button
            type="button"
            onClick={() => actions.peek(entry.item!.key)}
            className="shrink-0 font-mono text-meta text-accent-text hover:underline cursor-pointer"
          >
            {entry.item.key}
          </button>
        ) : (
          <span className="shrink-0 text-meta font-medium text-fg-secondary">{label}</span>
        )}
        {editing === "duration" ? (
          <input
            autoFocus
            value={draft}
            aria-label="Duration"
            data-duration-input
            onChange={(event) => setDraft(event.target.value)}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === "Enter") commit();
              if (event.key === "Escape") setEditing(null);
            }}
            className="w-16 rounded border border-strong bg-base px-1 text-meta text-heading outline-focus focus-visible:outline-2"
          />
        ) : (
          <button
            type="button"
            disabled={mirrored}
            onDoubleClick={() => begin("duration")}
            title={mirrored ? undefined : "Double-click to type a duration"}
            data-duration
            className="font-medium tabular-nums text-heading"
          >
            {durationText(seconds)}
          </button>
        )}
        {mirrored && <MirroredBadge source={entry.external_source} />}
        {!mirrored && (
          <button
            type="button"
            onClick={() => actions.remove(entry)}
            aria-label={`Delete ${label} ${durationText(seconds)}`}
            data-delete
            className="ml-auto rounded p-0.5 text-fg-muted hover:bg-base hover:text-fg cursor-pointer"
          >
            <X size={12} aria-hidden />
          </button>
        )}
      </header>
      <div onDoubleClick={() => begin("note")} className="min-h-0 flex-1" data-card-body>
        {entry.item && <p className="line-clamp-2 text-meta text-fg-secondary">{entry.item.title}</p>}
        {editing === "note" ? (
          <textarea
            autoFocus
            value={draft}
            rows={2}
            aria-label="Note"
            data-note-input
            onChange={(event) => setDraft(event.target.value)}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                commit();
              }
              if (event.key === "Escape") setEditing(null);
            }}
            className="mt-1 w-full resize-none rounded border border-strong bg-base px-1 text-meta text-fg outline-focus focus-visible:outline-2"
          />
        ) : (
          entry.note && <p className="mt-0.5 line-clamp-2 text-meta italic text-fg-muted">{entry.note}</p>
        )}
      </div>
      {!mirrored && (
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="Drag to change the duration"
          data-resize
          onPointerDown={onResizeDown}
          onPointerMove={onResizeMove}
          onPointerUp={onResizeUp}
          onPointerCancel={onResizeUp}
          className="absolute inset-x-0 bottom-0 h-2 cursor-ns-resize rounded-b-md bg-strong/40 opacity-0 group-hover/card:opacity-100 group-focus-visible/card:opacity-100"
        />
      )}
    </article>
  );
}
