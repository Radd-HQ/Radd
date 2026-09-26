import { AlertTriangle, CheckCircle2, CircleAlert, Loader2, Undo2, X } from "lucide-react";
import { Button, relativeTime, Td } from "@radd/plugin-sdk";
import { ProblemList } from "./ProblemList";
import { DryRunPreview, PlanSnapshot } from "./RunDetail";
import {
  JIRA_RUN_STAGE_LABELS,
  JiraRunStage,
  RunKind,
  TERMINAL_JIRA_RUN_STAGES,
  type JiraRun,
} from "./types";

const isRunning = (run: JiraRun) => !TERMINAL_JIRA_RUN_STAGES.includes(run.stage);

/** "6 issues skipped · 7 values dropped" — the headline, not a raw problem count. */
function problemSummary(run: JiraRun): string {
  const parts: string[] = [];
  if (run.counts.skipped) parts.push(`${run.counts.skipped} skipped`);
  if (run.counts.values_dropped) parts.push(`${run.counts.values_dropped} values dropped`);
  const causes = new Set(run.problems.map((p) => p.message));
  if (parts.length === 0) parts.push(`${causes.size} problem${causes.size === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

/** Counts worth surfacing, in pipeline order. */
const COUNT_LABELS: [string, string][] = [
  ["items", "issues created"],
  ["items_updated", "issues refreshed"],
  ["skipped", "issues skipped"],
  ["comments", "comments"],
  ["worklogs", "worklogs"],
  ["parents_linked", "parents linked"],
  ["links", "links created"],
  ["links_pending", "links waiting for another project"],
  ["parents_pending", "parents waiting for another project"],
  ["relinked", "references resolved"],
  ["fields_created", "custom fields created"],
  ["states_created", "workflow states created"],
  ["issue_types_created", "issue types created"],
  ["users_created", "placeholder accounts created"],
  ["cycles_created", "cycles created"],
  ["releases_created", "releases created"],
  ["rolled_back", "rows removed"],
  ["restored", "rows restored"],
];

/** One run, and — expanded — its counts, dry-run preview, problems and executed plan. */
export function RunRow({
  run,
  expanded,
  onToggle,
  onCancel,
  onRollback,
  onRerun,
  onFix,
}: {
  run: JiraRun;
  expanded: boolean;
  onToggle: () => void;
  onCancel: () => void;
  onRollback: () => void;
  onRerun?: (planId: string) => void;
  onFix?: (planId: string, section: string, mappingKey: string) => void;
}) {
  const running = isRunning(run);
  const counts = COUNT_LABELS.filter(([key]) => (run.counts[key] ?? 0) > 0);
  return (
    <>
      <tr>
        <Td>
          <button
            type="button"
            onClick={onToggle}
            className="text-left text-heading hover:text-accent-text cursor-pointer"
          >
            {run.dry_run ? "Dry run" : run.kind === RunKind.rollback ? "Rollback" : "Import"}
          </button>
          <div className="mt-0.5 text-[11px] text-fg-faint">{relativeTime(run.created_at)}</div>
        </Td>
        <Td className="text-xs text-fg-secondary">
          {counts.length === 0 ? (
            <span className="text-fg-faint">—</span>
          ) : (
            counts
              .slice(0, 3)
              .map(([key, label]) => `${run.counts[key]} ${label}`)
              .join(" · ")
          )}
          {/* A run that skipped issues must not read as an unqualified success. */}
          {run.problems.length > 0 && (
            <button
              type="button"
              onClick={onToggle}
              className="mt-0.5 flex items-center gap-1 text-status-warning-ink hover:underline cursor-pointer"
            >
              <AlertTriangle size={12} />
              {problemSummary(run)} — what to fix
            </button>
          )}
        </Td>
        <Td>
          <StageCell run={run} />
        </Td>
        <Td>
          <div className="flex items-center justify-end gap-1">
            {running ? (
              <Button size="sm" variant="ghost" onClick={onCancel}>
                <X size={13} /> Cancel
              </Button>
            ) : (
              <>
                {onRerun && run.plan_id && (
                  <Button size="sm" variant="ghost" onClick={() => onRerun(run.plan_id!)}>
                    Open plan
                  </Button>
                )}
                {!run.dry_run && run.kind === RunKind.import && (
                  <Button size="sm" variant="danger-ghost" onClick={onRollback}>
                    <Undo2 size={13} /> Undo
                  </Button>
                )}
              </>
            )}
          </div>
        </Td>
      </tr>
      {expanded && (
        <tr>
          <Td colSpan={4}>
            <div className="flex flex-col gap-2 py-1">
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-secondary">
                {counts.map(([key, label]) => (
                  <span key={key}>
                    <span className="text-heading">{run.counts[key]}</span> {label}
                  </span>
                ))}
              </div>
              {run.dry_run && (run.report.rows?.length ?? 0) > 0 && <DryRunPreview run={run} />}
              <ProblemList
                problems={run.problems}
                label="issue"
                onFix={
                  onFix && run.plan_id
                    ? (section, key) => onFix(run.plan_id!, section, key)
                    : undefined
                }
              />
              <PlanSnapshot run={run} />
            </div>
          </Td>
        </tr>
      )}
    </>
  );
}

function StageCell({ run }: { run: JiraRun }) {
  const label = JIRA_RUN_STAGE_LABELS[run.stage] ?? run.stage;
  if (run.stage === JiraRunStage.done) {
    // "Done" with skipped issues is not a clean result, and colouring it green
    // hides exactly the thing you need to act on.
    const blocked = (run.counts.skipped ?? 0) > 0;
    if (blocked || run.problems.length > 0) {
      return (
        <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-status-warning-ink">
          <AlertTriangle size={13} /> {blocked ? "Done, with skips" : "Done, with warnings"}
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-status-success-ink">
        <CheckCircle2 size={13} /> {label}
      </span>
    );
  }
  if (run.stage === JiraRunStage.failed || run.stage === JiraRunStage.canceled) {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-status-danger-ink">
        <CircleAlert size={13} /> {label}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-fg-secondary">
      <Loader2 size={13} className="animate-spin" /> {label}
    </span>
  );
}
