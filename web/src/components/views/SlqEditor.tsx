import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { CircleAlert, CircleCheck, CornerDownLeft, LoaderCircle } from "lucide-react";
import { SlqProbeStatus, useSlqAutocomplete, type SlqProbe } from "../../lib/hooks";
import { slqErrorContext } from "../../lib/slq";
import { applySuggestion, type SlqSuggestion } from "../../lib/slq-suggest";
import { SlqSuggestDropdown } from "./SlqSuggestDropdown";

interface SlqEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Probe for THIS draft (validation while typing; run state once committed). */
  probe: SlqProbe;
  /**
   * Autocomplete scope: an optional project_id. Omit (null) to disable
   * autocomplete (validation line still works). Values are queried live.
   */
  suggestScope?: Record<string, string> | null;
  /** Which SLQ dialect's endpoints to validate/complete against (spec 98). */
  dialect?: string;
  /** Single-line styling for the ad-hoc list bar. */
  compact?: boolean;
  /** Compact only: Enter (with the dropdown closed) commits the query. */
  onSubmit?: () => void;
  /** Grab focus on mount — a user-initiated mode switch, never page load. */
  autoFocus?: boolean;
  label?: string;
  placeholder?: string;
}

/**
 * SLQ query editor (spec 11) with server-driven autocomplete (spec 13):
 * monospace textarea + live validation line, plus a Jira-style suggestion
 * dropdown fed by `GET /items/slq/suggest`. Typing (and Ctrl+Space) asks the
 * server what the caret wants; ↑/↓ navigate, Enter/Tab accept, Esc closes.
 * The caller owns the probe so routes reuse the same fetch as their result list.
 */
export function SlqEditor({
  value,
  onChange,
  probe,
  suggestScope,
  dialect,
  compact = false,
  onSubmit,
  autoFocus = false,
  label,
  placeholder = "state != Done AND assignee = me ORDER BY updated DESC",
}: SlqEditorProps) {
  const id = useId();
  const statusId = `${id}-status`;
  const invalid = probe.status === SlqProbeStatus.invalid;

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pendingCaretRef = useRef<number | null>(null);
  // True once the user arrow-keyed/hovered into the dropdown — gates whether
  // Enter accepts a suggestion (navigated) or runs the query (compact bars).
  const navigatedRef = useRef(false);
  const ac = useSlqAutocomplete(suggestScope ?? null, dialect);
  const { request, close } = ac;

  // After an accepted suggestion re-renders the controlled value, restore the
  // caret and chain into the next context (operators after a field, etc.).
  useEffect(() => {
    const caret = pendingCaretRef.current;
    if (caret === null) return;
    pendingCaretRef.current = null;
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(caret, caret);
    request(value, caret, true);
  }, [value, request]);

  function accept(suggestion: SlqSuggestion | null): boolean {
    const el = textareaRef.current;
    if (!suggestion || suggestion.insert === "" || !el) return false;
    const cursor = el.selectionStart ?? value.length;
    const result = applySuggestion(value, ac.replaceFrom, cursor, suggestion.insert);
    pendingCaretRef.current = result.cursor;
    navigatedRef.current = false;
    onChange(result.value);
    ac.close();
    return true;
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.code === "Space" && event.ctrlKey) {
      event.preventDefault();
      const el = event.currentTarget;
      request(el.value, el.selectionStart ?? el.value.length, true);
      return;
    }
    if (event.key === "Escape") {
      // Always cancel — including a still-debouncing suggest request, so a
      // late response can't pop the dropdown open after dismissal. When the
      // dropdown is closed the event falls through (modal Esc still works).
      close();
      navigatedRef.current = false;
      if (ac.open) return event.preventDefault();
    }
    if (ac.open) {
      if (event.key === "ArrowDown") {
        navigatedRef.current = true;
        return event.preventDefault(), ac.moveActive(1);
      }
      if (event.key === "ArrowUp") {
        navigatedRef.current = true;
        return event.preventDefault(), ac.moveActive(-1);
      }
      // Tab always accepts. Enter accepts too — except in a compact bar where
      // the user never navigated the dropdown: there Enter means "run" (the
      // Jira rule — arrow/hover into a suggestion first if you want it).
      const enterAccepts = event.key === "Enter" && (!compact || navigatedRef.current);
      if ((event.key === "Tab" || enterAccepts) && accept(ac.activeSuggestion()))
        return event.preventDefault();
    }
    // Compact = a query bar: Enter never grows it into a second line — it
    // commits the query instead (spec 55: run-on-Enter).
    if (compact && event.key === "Enter") {
      event.preventDefault();
      close();
      onSubmit?.();
    }
  }

  return (
    <div className={compact ? "relative flex min-w-0 flex-1 flex-col" : "flex flex-col gap-1.5"}>
      {label && (
        <label htmlFor={id} className="text-xs font-medium text-fg-secondary">
          {label}
        </label>
      )}
      <div className="relative">
        <textarea
          id={id}
          ref={textareaRef}
          autoFocus={autoFocus}
          value={value}
          onChange={(event) => {
            navigatedRef.current = false;
            onChange(event.target.value);
            request(event.target.value, event.target.selectionStart ?? event.target.value.length);
          }}
          onKeyDown={handleKeyDown}
          onBlur={close}
          rows={compact ? 1 : 3}
          spellCheck={false}
          placeholder={placeholder}
          aria-label={label ?? "SLQ query"}
          aria-invalid={invalid || undefined}
          aria-describedby={statusId}
          aria-autocomplete="list"
          aria-expanded={ac.open}
          className={
            compact
              ? // FRAMELESS: the compact editor lives inside the QueryBar
                // pill, which owns the border/background/focus treatment —
                // a second box in the box is what made SLQ mode look heavier
                // than Ask mode. Invalid state reads from the status line.
                // `block`: an inline-block textarea rides the text baseline
                // and drags ~6px of descender space into its wrapper.
                "block h-7 w-full resize-none overflow-hidden bg-transparent px-0 py-1 font-mono " +
                "text-xs leading-5 text-fg outline-none placeholder:text-fg-faint"
              : "block w-full resize-none rounded-md border bg-base/60 px-2.5 py-2 font-mono text-[13px] " +
                "leading-5 text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 " +
                (invalid
                  ? "border-red-500/60 focus:outline-red-400"
                  : "border-strong focus:outline-focus")
          }
        />
        {ac.open && (
          <SlqSuggestDropdown
            suggestions={ac.suggestions}
            activeIndex={ac.activeIndex}
            contextLabel={ac.contextLabel}
            onHover={(index) => {
              navigatedRef.current = true;
              ac.setActiveIndex(index);
            }}
            onPick={accept}
          />
        )}
      </div>
      {/* Compact: the status FLOATS below the bar as an anchored hint card —
          in-flow it would grow the fixed-height top bar and the overflow
          painted over the page header (and swallowed pointer events). The
          empty:hidden keeps the empty container from rendering a ghost card.
          Non-compact (modals): in-flow under the editor as always. */}
      <div
        id={statusId}
        aria-live="polite"
        className={
          compact
            ? // z-20 — BELOW the autocomplete dropdown (z-30): both anchor
              // under the input, and while suggestions are open they are the
              // active UI; the validation hint waits underneath.
              "absolute left-0 right-0 top-full z-20 mt-2 rounded-md border border-subtle bg-surface px-2.5 py-1.5 shadow-pop empty:hidden"
            : "empty:hidden"
        }
      >
        <ProbeStatusLine probe={probe} compact={compact} />
      </div>
    </div>
  );
}

/** The one-line (or error-block) outcome under the editor. */
function ProbeStatusLine({ probe, compact }: { probe: SlqProbe; compact: boolean }) {
  switch (probe.status) {
    case SlqProbeStatus.idle:
      // The ad-hoc bar needs no hint while inactive; the modal editor does.
      return compact ? null : (
        <p className="text-xs text-fg-faint">Empty query — matches every item in scope.</p>
      );
    case SlqProbeStatus.checking:
      return (
        <p className="flex items-center gap-1 text-xs text-fg-muted">
          <LoaderCircle size={12} className="animate-spin" aria-hidden />
          Checking…
        </p>
      );
    case SlqProbeStatus.ready:
      return (
        <p className="flex items-center gap-1 text-xs text-fg-muted">
          <CornerDownLeft size={12} aria-hidden />
          Valid — press Enter to run
        </p>
      );
    case SlqProbeStatus.valid:
      return (
        <p className="flex items-center gap-1 text-xs text-emerald-400">
          <CircleCheck size={12} aria-hidden />
          {probe.count === undefined
            ? "Query is valid"
            : probe.atCap
              ? `${probe.count}+ items match`
              : `${probe.count} ${probe.count === 1 ? "item matches" : "items match"}`}
        </p>
      );
    case SlqProbeStatus.invalid:
      return <SlqErrorBlock query={probe.query} message={probe.error?.message ?? "Invalid query"} position={probe.error?.position ?? null} />;
    case SlqProbeStatus.failed:
      return (
        <p className="flex items-center gap-1 text-xs text-amber-400">
          <CircleAlert size={12} aria-hidden />
          Could not check the query: {probe.failure}
        </p>
      );
  }
}

interface SlqErrorBlockProps {
  query: string;
  message: string;
  position: number | null;
}

/** Parse-error rendering: message + the offending line with a caret under it. */
export function SlqErrorBlock({ query, message, position }: SlqErrorBlockProps) {
  const context = position === null ? null : slqErrorContext(query, position);
  return (
    <div className="flex flex-col gap-1" role="alert">
      <p className="flex items-center gap-1 text-xs text-red-400">
        <CircleAlert size={12} className="shrink-0" aria-hidden />
        {message}
      </p>
      {context && (
        <pre className="overflow-x-auto rounded border border-red-500/30 bg-red-500/5 px-2 py-1 font-mono text-[11px] leading-4 text-fg">
          {context.line}
          {"\n"}
          <span className="text-red-400">{context.caret}</span>
        </pre>
      )}
    </div>
  );
}
