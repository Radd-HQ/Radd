/**
 * Recorded runs of one automation (RADD-1266).
 *
 * The engine kept nothing of a run but a log line, so "did it fire, what did
 * it skip, why" had no answer in the product. Each run is stored in the dry
 * run's own shape, and this panel renders it through the same view the dry run
 * uses — one renderer for "what would it do" and "what did it do". Selecting a
 * run also hands its report up, so the canvas labels its ports with what
 * actually happened.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History, CircleSlash } from "lucide-react";
import { automationRunQuery, automationRunsQuery } from "../../lib/queries";
import { relativeTime, shortDateTime } from "../../lib/dates";
import { RunStatus, type AutomationNode, type AutomationRun, type RuleTestResult } from "../../lib/types";
import { RunResultView } from "./RuleTestPanel";

interface RunsPanelProps {
  ruleId: string;
  nodes?: AutomationNode[];
  /** Hand the selected run's report up so the canvas can label its ports. */
  onResult?: (result: RuleTestResult | null) => void;
}

export const RUN_STATUS_LABEL: Record<string, string> = {
  [RunStatus.applied]: "Applied",
  [RunStatus.nothingToDo]: "Nothing to do",
  [RunStatus.refused]: "Refused",
  [RunStatus.failed]: "Failed",
};

/** The status chip, shared with the automations list. */
export function RunStatusChip({ status }: { status: string }) {
  const tone =
    status === RunStatus.applied
      ? "bg-emerald-500/15 text-emerald-300"
      : status === RunStatus.failed || status === RunStatus.refused
        ? "bg-status-danger/15 text-status-danger"
        : "bg-elevated text-fg-secondary";
  return (
    <span
      data-run-status={status}
      className={`shrink-0 rounded px-1.5 py-px text-[10px] uppercase tracking-wide ${tone}`}
    >
      {RUN_STATUS_LABEL[status] ?? status}
    </span>
  );
}

const SOURCE_LABEL: Record<AutomationRun["source"], string> = {
  event: "event",
  schedule: "schedule",
  manual: "manual",
};

export function RunsPanel({ ruleId, nodes = [], onResult }: RunsPanelProps) {
  const runs = useQuery(automationRunsQuery(ruleId));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useQuery({ ...automationRunQuery(ruleId, selectedId ?? ""), enabled: Boolean(selectedId) });

  const select = (run: AutomationRun) => {
    const next = run.id === selectedId ? null : run.id;
    setSelectedId(next);
    if (next === null) onResult?.(null);
  };
  // The report reaches the canvas once it is LOADED, not on click: handing up a
  // stale one from the previous selection would label the ports with the wrong
  // run for a moment, which reads as a bug rather than a delay.
  const report = detail.data?.id === selectedId ? detail.data?.report ?? null : null;
  useEffect(() => {
    if (report !== null) onResult?.(report);
    // `onResult` is a setState from the editor and stable; the report identity
    // is what should re-run this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report]);

  return (
    <div className="flex flex-col gap-3 rounded-md border border-subtle bg-surface/40 p-3" data-runs-panel>
      <div className="flex items-center gap-2">
        <History size={14} className="text-accent-text" aria-hidden />
        <span className="text-xs font-medium text-fg">Runs</span>
        <span className="text-[11px] text-fg-muted">
          What each run did — every node, every action, and why one skipped.
        </span>
      </div>

      {runs.isPending && <p className="text-xs text-fg-muted">Loading runs…</p>}
      {runs.data && runs.data.length === 0 && (
        <p className="flex items-center gap-1.5 text-[13px]">
          <CircleSlash size={14} className="text-fg-muted" aria-hidden />
          <span className="text-fg-secondary">This automation has not run yet.</span>
        </p>
      )}
      {runs.data && runs.data.length > 0 && (
        <ul className="flex flex-col gap-0.5" data-runs-list>
          {runs.data.map((run) => (
            <li key={run.id}>
              <button
                type="button"
                data-run-row={run.id}
                aria-expanded={run.id === selectedId}
                onClick={() => select(run)}
                className={`flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded border px-2.5 py-1.5 text-left text-xs cursor-pointer hover:bg-elevated ${
                  run.id === selectedId ? "border-emphasis bg-elevated" : "border-subtle/80 bg-base/40"
                }`}
              >
                <RunStatusChip status={run.status} />
                <span className="font-medium text-fg" title={shortDateTime(run.started_at)}>
                  {relativeTime(run.started_at)}
                </span>
                <span className="text-[11px] text-fg-muted">
                  {SOURCE_LABEL[run.source]}
                  {run.event_type && run.source === "event" ? ` · ${run.event_type}` : ""}
                  {` · from ${run.trigger_node_id}`}
                </span>
                {run.item_keys.length > 0 && (
                  <span className="text-[11px] text-fg-secondary">{run.item_keys.slice(0, 4).join(", ")}</span>
                )}
                <span className="ml-auto text-[11px] text-fg-faint">
                  {run.actions_applied} applied
                  {run.actions_skipped > 0 ? ` · ${run.actions_skipped} skipped` : ""}
                </span>
                {run.error && <span className="w-full text-[11px] text-status-danger">{run.error}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      {selectedId && detail.isPending && <p className="text-xs text-fg-muted">Loading the report…</p>}
      {selectedId && report && <RunResultView result={report} nodes={nodes} applied />}
      {selectedId && detail.data && !report && detail.data.id === selectedId && (
        <p className="text-xs text-fg-muted">This run left no report{detail.data.error ? `: ${detail.data.error}` : "."}</p>
      )}
    </div>
  );
}
