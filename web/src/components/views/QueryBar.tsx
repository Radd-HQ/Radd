import { useIsAuthenticated } from "../../lib/hooks";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { SearchCode, Sparkles } from "lucide-react";
import { api } from "../../lib/api";
import { aiErrorText, isAiGone } from "../../lib/ai";
import { ApiPath } from "../../lib/constants";
import { aiStatusQuery } from "../../lib/queries";
import type { SlqPageFilter } from "../../lib/slq-filter";
import type { NlQueryRequest, NlQueryResponse } from "../../lib/types";
import { SlqEditor } from "./SlqEditor";
import { modShortcut } from "../../lib/platform";

const QueryMode = { slq: "slq", ask: "ask" } as const;
type QueryModeValue = (typeof QueryMode)[keyof typeof QueryMode];

interface QueryBarProps {
  filter: SlqPageFilter;
  /** Narrows autocomplete to a project's fields/states when the page has one. */
  projectId?: string;
  /** SLQ dialect endpoints (spec 98) — the timesheet queries WORKLOGS. */
  dialect?: string;
  /** The NL ask's target surface; defaults to the item dialect. */
  nlDialect?: "items" | "worklog";
  placeholder?: string;
}

/**
 * ONE query input, two modes (the SLQ ⟷ Ask toggle at the pill's end): Ask
 * mode is the default on an empty bar — natural language in, POST /slq/nl
 * generates the query, and the bar flips to SLQ mode with the generated query
 * sitting in the editor, applied — transparency over magic, and every ask
 * teaches the query language. SLQ mode is the full editor — autocomplete,
 * validation, run-on-Enter — and a bar that arrives with a query already in
 * it (URL-synced state) starts there so the applied query stays visible.
 * The mod+I shortcut toggles the modes while the bar is focused. The toggle only exists
 * while AI is enabled; without it the bar is simply the SLQ editor. A
 * deliberate NON-feature: no auto-detection — a typo'd SLQ must fail loudly
 * as SLQ, never silently become an LLM prompt.
 */
export function QueryBar({
  filter,
  projectId,
  dialect,
  nlDialect = "items",
  placeholder = "Filter with SLQ: priority IN (high, blocker) AND assignee = me",
}: QueryBarProps) {
  const status = useQuery({ ...aiStatusQuery, enabled: useIsAuthenticated() });
  // null = no explicit choice yet: default to Ask on an empty bar, SLQ when a
  // query is already sitting in the editor. Explicit user switches stick.
  const [mode, setMode] = useState<QueryModeValue | null>(null);
  const [question, setQuestion] = useState("");

  const ask = useMutation({
    mutationFn: (body: NlQueryRequest) => api.post<NlQueryResponse>(ApiPath.slqNl, body),
    onSuccess: (data) => {
      filter.runQuery(data.slq);
      setMode(QueryMode.slq);
      setQuestion("");
    },
  });
  const askAvailable = Boolean(status.data?.enabled) && !isAiGone(ask.error);
  const effectiveMode = mode ?? (filter.draft ? QueryMode.slq : QueryMode.ask);
  const askMode = effectiveMode === QueryMode.ask && askAvailable;
  // Focus-stealing guard: only a user-initiated switch autofocuses the newly
  // mounted input — the page-load default must never grab keyboard focus.
  const userSwitched = mode !== null;

  const submitAsk = () => {
    const trimmed = question.trim();
    if (trimmed && !ask.isPending) ask.mutate({ question: trimmed, dialect: nlDialect });
  };

  return (
    // relative: the ask status lines float below the pill (anchored overlay)
    // so they never grow the fixed-height top bar.
    <div className="relative flex min-w-0 flex-1 flex-col">
      <div
        className="flex min-w-0 items-start gap-2 rounded-md border border-subtle bg-surface px-3 py-1 focus-within:border-strong"
        onKeyDown={(event) => {
          // Cmd/Ctrl+I flips the mode from either input (scoped to the bar,
          // so pages with several query bars toggle only the focused one).
          if (
            (event.metaKey || event.ctrlKey) &&
            !event.shiftKey &&
            !event.altKey &&
            event.key.toLowerCase() === "i" &&
            askAvailable
          ) {
            event.preventDefault();
            setMode(askMode ? QueryMode.slq : QueryMode.ask);
          }
        }}
      >
        {askMode ? (
          <Sparkles size={13} className="mt-1.5 shrink-0 text-accent-text" aria-hidden />
        ) : (
          <SearchCode size={13} className="mt-1.5 shrink-0 text-fg-faint" aria-hidden />
        )}
        {askMode ? (
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submitAsk();
              }
              if (event.key === "Escape") setMode(QueryMode.slq);
            }}
            placeholder="Ask: open bugs assigned to me — the answer lands as an SLQ query"
            aria-label="Ask AI for a query"
            autoFocus={userSwitched}
            maxLength={2000}
            disabled={ask.isPending}
            // Metrics mirror the SLQ editor exactly (mono, size, leading,
            // color) so toggling modes moves NOTHING but the icon/placeholder.
            className="block h-7 min-w-0 flex-1 bg-transparent py-1 font-mono text-xs leading-5 text-fg outline-none placeholder:text-fg-faint disabled:opacity-60"
          />
        ) : (
          <SlqEditor
            value={filter.draft}
            onChange={(value) => {
              // Editing the query dismisses the floating ask explanation.
              if (ask.data || ask.isError) ask.reset();
              filter.setDraft(value);
            }}
            probe={filter.probe}
            suggestScope={projectId ? { project_id: projectId } : {}}
            dialect={dialect}
            compact
            autoFocus={userSwitched}
            onSubmit={filter.run}
            placeholder={placeholder}
          />
        )}
        {askAvailable && (
          <div
            role="group"
            aria-label="Query mode"
            className="mt-0.5 flex shrink-0 items-center gap-0.5 rounded-md border border-subtle p-0.5"
          >
            <button
              type="button"
              aria-pressed={!askMode}
              title={`SLQ mode — ${modShortcut("I")} toggles`}
              onClick={() => setMode(QueryMode.slq)}
              className={
                "rounded px-1.5 py-0.5 font-mono text-[10px] cursor-pointer transition-colors " +
                (!askMode ? "bg-elevated text-heading" : "text-fg-muted hover:text-fg")
              }
            >
              SLQ
            </button>
            <button
              type="button"
              aria-pressed={askMode}
              title={`Ask mode — ${modShortcut("I")} toggles`}
              onClick={() => setMode(QueryMode.ask)}
              className={
                "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] cursor-pointer transition-colors " +
                (askMode ? "bg-elevated text-heading" : "text-fg-muted hover:text-fg")
              }
            >
              <Sparkles size={10} aria-hidden />
              Ask
            </button>
          </div>
        )}
      </div>
      {(askMode && ask.isPending) || ask.isError || ask.data?.explanation ? (
        <div className="absolute left-0 right-0 top-full z-20 mt-2 rounded-md border border-subtle bg-surface px-2.5 py-1.5 shadow-pop">
          {askMode && ask.isPending ? (
            <p className="text-[11px] text-fg-faint">Asking…</p>
          ) : ask.isError ? (
            <p className="text-[11px] text-red-400">{aiErrorText(ask.error)}</p>
          ) : (
            <p className="text-[11px] text-fg-faint">{ask.data?.explanation}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
