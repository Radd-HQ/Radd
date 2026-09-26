import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { SearchCode } from "lucide-react";
import {
  QueryDialect,
  errorMessage,
  useQueryInputModes,
  type QueryDialectValue,
  type QueryDraft,
  type QueryInputMode,
} from "@radd/plugin-sdk";
import { ApiPath } from "../../lib/constants";
import type { SlqPageFilter } from "../../lib/slq-filter";
import { SlqEditor } from "./SlqEditor";
import { modShortcut } from "../../lib/platform";

/** The bar's own mode; every other is a contributed input mode's id (`<plugin>.<name>`). */
const SLQ = "slq";

/** Where each dialect's SLQ endpoints live (spec 98): validation and autocomplete. */
const DIALECT_ENDPOINT: Record<QueryDialectValue, string> = {
  [QueryDialect.items]: ApiPath.items,
  [QueryDialect.worklog]: ApiPath.timesheet,
};

interface QueryBarProps {
  filter: SlqPageFilter;
  /** Narrows autocomplete to a project's fields/states when the page has one. */
  projectId?: string;
  /** The SLQ dialect the bar queries (spec 98) — the timesheet queries WORKLOGS. */
  dialect?: QueryDialectValue;
  placeholder?: string;
}

/**
 * ONE query input. SLQ is the bar's own mode — the full editor: autocomplete, validation,
 * run-on-Enter. Plugins contribute INPUT MODES (RADD-1400): free text in, SLQ out. With any
 * available, a toggle sits at the pill's end, mod+I cycles the modes while the bar is focused,
 * and an EMPTY bar opens on the first one; a bar that arrives with a query already in it
 * (URL-synced state) starts in SLQ so the applied query stays visible, and an explicit switch
 * sticks. A mode's answer lands in the SLQ editor, applied, with its explanation floating below —
 * transparency over magic, every answer teaches the query language. A deliberate NON-feature: no
 * auto-detection — a typo'd SLQ must fail loudly as SLQ, never silently become a mode's input.
 * With no mode available the bar is simply the SLQ editor.
 */
export function QueryBar({
  filter,
  projectId,
  dialect = QueryDialect.items,
  placeholder = "Filter with SLQ: priority IN (high, blocker) AND assignee = me",
}: QueryBarProps) {
  const { modes, gates } = useQueryInputModes(dialect);
  // null = no explicit choice yet: the first mode on an empty bar, SLQ when a query is already
  // sitting in the editor. Explicit user switches stick.
  const [choice, setChoice] = useState<string | null>(null);
  const [text, setText] = useState("");
  const running = useRef<{ controller: AbortController; mode: QueryInputMode } | null>(null);

  const draft = useMutation({
    mutationFn: async ({ mode, input }: { mode: QueryInputMode; input: string }): Promise<QueryDraft> => {
      running.current?.controller.abort();
      const controller = new AbortController();
      running.current = { controller, mode };
      try {
        const result = await mode.toQuery(input, { dialect, signal: controller.signal });
        if (controller.signal.aborted) throw new DOMException("The mode went away", "AbortError");
        return result;
      } finally {
        if (running.current?.controller === controller) running.current = null;
      }
    },
    onSuccess: (result) => {
      filter.runQuery(result.query);
      setChoice(SLQ);
      setText("");
    },
  });
  // A run whose mode is withdrawn (its plugin disabled) is aborted, and its draft dropped.
  const reset = draft.reset;
  useEffect(() => {
    const run = running.current;
    if (run && !modes.some((mode) => mode.id === run.mode.id && mode.generation === run.mode.generation)) {
      running.current = null;
      run.controller.abort();
      reset();
    }
  }, [modes, reset]);
  useEffect(() => () => running.current?.controller.abort(), []);

  const wanted = choice ?? (filter.draft ? SLQ : (modes[0]?.id ?? SLQ));
  const active = modes.find((mode) => mode.id === wanted) ?? null;
  // Focus-stealing guard: only a user-initiated switch autofocuses the newly
  // mounted input — the page-load default must never grab keyboard focus.
  const userSwitched = choice !== null;
  const failed = draft.isError && !(draft.error instanceof DOMException && draft.error.name === "AbortError");

  const submit = () => {
    const trimmed = text.trim();
    if (active && trimmed && !draft.isPending) draft.mutate({ mode: active, input: trimmed });
  };
  // SLQ, then each mode, then SLQ again.
  const cycle = () => {
    const order = [SLQ, ...modes.map((mode) => mode.id)];
    setChoice(order[(order.indexOf(active?.id ?? SLQ) + 1) % order.length]);
  };

  return (
    // relative: the status lines float below the pill (anchored overlay)
    // so they never grow the fixed-height top bar.
    <div className="relative flex min-w-0 flex-1 flex-col">
      {gates}
      <div
        className="flex min-w-0 items-start gap-2 rounded-md border border-subtle bg-surface px-3 py-1 focus-within:border-strong"
        onKeyDown={(event) => {
          // Cmd/Ctrl+I cycles the modes from either input (scoped to the bar,
          // so pages with several query bars switch only the focused one).
          if (
            (event.metaKey || event.ctrlKey) &&
            !event.shiftKey &&
            !event.altKey &&
            event.key.toLowerCase() === "i" &&
            modes.length > 0
          ) {
            event.preventDefault();
            cycle();
          }
        }}
      >
        <LeadingIcon mode={active} />
        {active ? (
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submit();
              }
              if (event.key === "Escape") setChoice(SLQ);
            }}
            placeholder={active.placeholder}
            title={active.hint}
            aria-label={active.ariaLabel ?? active.placeholder}
            data-query-input-mode={active.id}
            autoFocus={userSwitched}
            maxLength={2000}
            disabled={draft.isPending}
            // Metrics mirror the SLQ editor exactly (mono, size, leading,
            // color) so toggling modes moves NOTHING but the icon/placeholder.
            className="block h-7 min-w-0 flex-1 bg-transparent py-1 font-mono text-xs leading-5 text-fg outline-none placeholder:text-fg-faint disabled:opacity-60"
          />
        ) : (
          <SlqEditor
            value={filter.draft}
            onChange={(value) => {
              // Editing the query dismisses the floating explanation.
              if (draft.data || draft.isError) draft.reset();
              filter.setDraft(value);
            }}
            probe={filter.probe}
            suggestScope={projectId ? { project_id: projectId } : {}}
            dialect={DIALECT_ENDPOINT[dialect]}
            compact
            autoFocus={userSwitched}
            onSubmit={filter.run}
            placeholder={placeholder}
          />
        )}
        {modes.length > 0 && (
          <div
            role="group"
            aria-label="Query mode"
            className="mt-0.5 flex shrink-0 items-center gap-0.5 rounded-md border border-subtle p-0.5"
          >
            <button
              type="button"
              aria-pressed={!active}
              title={`SLQ mode — ${modShortcut("I")} toggles`}
              onClick={() => setChoice(SLQ)}
              className={
                "rounded px-1.5 py-0.5 font-mono text-[10px] cursor-pointer transition-colors " +
                (!active ? "bg-elevated text-heading" : "text-fg-muted hover:text-fg")
              }
            >
              SLQ
            </button>
            {modes.map((mode) => {
              const Icon = mode.icon;
              const on = active?.id === mode.id;
              return (
                <button
                  key={mode.id}
                  type="button"
                  aria-pressed={on}
                  title={`${mode.label} mode — ${modShortcut("I")} toggles`}
                  onClick={() => setChoice(mode.id)}
                  data-query-mode-toggle={mode.id}
                  className={
                    "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] cursor-pointer transition-colors " +
                    (on ? "bg-elevated text-heading" : "text-fg-muted hover:text-fg")
                  }
                >
                  {Icon ? <Icon size={10} aria-hidden /> : null}
                  {mode.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
      {(active && draft.isPending) || failed || draft.data?.explanation ? (
        <div className="absolute left-0 right-0 top-full z-20 mt-2 rounded-md border border-subtle bg-surface px-2.5 py-1.5 shadow-pop">
          {active && draft.isPending ? (
            <p className="text-[11px] text-fg-faint">{active.busyLabel ?? "Working…"}</p>
          ) : failed ? (
            <p className="text-[11px] text-red-400">{errorMessage(draft.error)}</p>
          ) : (
            <p className="text-[11px] text-fg-faint" data-query-explanation>{draft.data?.explanation}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** The pill's leading icon: the mode's own, or SLQ's. */
function LeadingIcon({ mode }: { mode: QueryInputMode | null }) {
  const Icon = mode?.icon;
  if (Icon) return <Icon size={13} className="mt-1.5 shrink-0 text-accent-text" aria-hidden />;
  return <SearchCode size={13} className="mt-1.5 shrink-0 text-fg-faint" aria-hidden />;
}
