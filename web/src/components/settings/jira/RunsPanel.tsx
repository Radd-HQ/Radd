import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleAlert, Link2, Loader2, Undo2, X } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import { relativeTime } from "../../../lib/dates";
import { jiraPendingQuery, jiraRunsQuery, queryKeys } from "../../../lib/queries";
import {
  JIRA_RUN_STAGE_LABELS,
  JiraRunStage,
  RunKind,
  TERMINAL_JIRA_RUN_STAGES,
  type JiraRun,
  type PendingSummary,
  type RollbackPreflight,
} from "../../../lib/types";
import { Button } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { EmptyState } from "../../EmptyState";
import { QueryError } from "../../QueryError";
import { Table, TBody, Td, THead, Th } from "../../Table";
import { TableSkeleton } from "../../TableSkeleton";
import { ProblemList } from "./ProblemList";

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

/**
 * Dry runs, imports and rollbacks (spec 100), with the two repair actions spec 90
 * had no answer for: RELINK (resolve cross-project references once their target
 * arrives) and ROLLBACK (undo an import you do not like).
 */
export function RunsPanel({
  onRerun,
  onFix,
}: {
  onRerun?: (planId: string) => void;
  /** Open the mapping tab (and row) a problem points at. */
  onFix?: (planId: string, section: string, mappingKey: string) => void;
}) {
  const queryClient = useQueryClient();
  const runs = useQuery(jiraRunsQuery());
  const pending = useQuery(jiraPendingQuery());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmNode, confirm] = useConfirm();
  // The newest run with problems opens by default — the thing you came to read.
  const autoOpen = (runs.data ?? []).find((r) => r.problems.length > 0)?.id ?? null;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.jiraRuns });
    void queryClient.invalidateQueries({ queryKey: queryKeys.jiraPending });
  };

  const relink = useMutation({
    mutationFn: () => api.post<PendingSummary>(ApiPath.jiraRelink, {}),
    onSuccess: invalidate,
  });

  const rollback = useMutation({
    mutationFn: ({ id, includeSchema }: { id: string; includeSchema: boolean }) =>
      api.post<JiraRun>(`${ApiPath.jiraRuns}/${id}/rollback`, {
        include_schema: includeSchema,
        skip_edited: true,
      }),
    onSuccess: invalidate,
  });

  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`${ApiPath.jiraRuns}/${id}/cancel`, {}),
    onSuccess: invalidate,
  });

  const onRollback = async (run: JiraRun) => {
    const preflight = await api.get<RollbackPreflight>(`${ApiPath.jiraRuns}/${run.id}/rollback`);
    const edited = preflight.edited_since.length;
    const ok = await confirm({
      title: "Undo this import?",
      message: (
        <span>
          {preflight.total} row(s) would be undone.
          {edited > 0 && (
            <>
              {" "}
              <span className="text-amber-300">
                {edited} issue(s) have been edited since the import and will be LEFT ALONE.
              </span>
            </>
          )}{" "}
          The project and its fields are kept, so you can fix the mapping and import again.
        </span>
      ),
      confirmLabel: "Undo the issues",
      danger: true,
    });
    if (ok) rollback.mutate({ id: run.id, includeSchema: false });
  };

  return (
    <section className="rounded-lg border border-subtle bg-surface p-4">
      {confirmNode}
      <header className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-medium text-heading">Runs</h2>
          <p className="mt-0.5 text-xs text-fg-secondary">
            Dry runs, imports and rollbacks. Everything reads the local cache — no Jira needed.
          </p>
        </div>
        {(pending.data?.total ?? 0) > 0 && (
          <Button
            size="sm"
            variant="secondary"
            className="shrink-0"
            onClick={() => relink.mutate()}
            disabled={relink.isPending}
            title="Retry every cross-project reference against what is imported now"
          >
            <Link2 size={13} /> Relink {pending.data?.total}
          </Button>
        )}
      </header>

      {(pending.data?.total ?? 0) > 0 && (
        <p className="mb-3 rounded-md border border-subtle bg-elevated px-2.5 py-2 text-xs text-fg-secondary">
          Waiting for a target that is not imported yet:{" "}
          {Object.entries(pending.data?.by_project ?? {})
            .map(([prefix, count]) => `${count} × ${prefix}-*`)
            .join(", ")}
          . Import those projects, or press Relink after you do.
        </p>
      )}

      {runs.isPending ? (
        <TableSkeleton rows={2} />
      ) : runs.isError ? (
        <QueryError label="import runs" error={runs.error} />
      ) : runs.data.length === 0 ? (
        <EmptyState icon={CheckCircle2} message="No runs yet — dry-run a plan to see what it would do." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Run</Th>
                <Th>Result</Th>
                <Th>Status</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </THead>
            <TBody>
              {runs.data.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  expanded={expanded === run.id || (autoOpen === run.id && expanded === null)}
                  onToggle={() => setExpanded((id) => (id === run.id ? null : run.id))}
                  onCancel={() => cancel.mutate(run.id)}
                  onRollback={() => void onRollback(run)}
                  onRerun={onRerun}
                  onFix={onFix}
                />
              ))}
            </TBody>
          </Table>
        </div>
      )}
      {(rollback.isError || relink.isError) && (
        <p className="mt-2 text-xs text-red-400">
          {errorMessage(rollback.error ?? relink.error)}
        </p>
      )}
    </section>
  );
}

function RunRow({
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
              className="mt-0.5 flex items-center gap-1 text-amber-400 hover:text-amber-300 cursor-pointer"
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
              {run.dry_run && (run.report.rows?.length ?? 0) > 0 && (
                <DryRunPreview run={run} />
              )}
              <ProblemList
                problems={run.problems}
                label="issue"
                onFix={
                  onFix && run.plan_id
                    ? (section, key) => onFix(run.plan_id!, section, key)
                    : undefined
                }
              />
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
        <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-amber-400">
          <AlertTriangle size={13} /> {blocked ? "Done, with skips" : "Done, with warnings"}
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-emerald-400">
        <CheckCircle2 size={13} /> {label}
      </span>
    );
  }
  if (run.stage === JiraRunStage.failed || run.stage === JiraRunStage.canceled) {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-red-400">
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

/** What the import would do, issue by issue — the thing spec 90 never showed. */
function DryRunPreview({ run }: { run: JiraRun }) {
  const rows = run.report.rows ?? [];
  const problems = rows.filter((r) => r.action === "skip");
  const [onlyProblems, setOnlyProblems] = useState(problems.length > 0);
  const shown = (onlyProblems ? problems : rows).slice(0, 100);
  return (
    <div className="rounded-md border border-subtle">
      <div className="flex items-center gap-2 border-b border-subtle px-2.5 py-1.5">
        <span className="text-xs text-fg-secondary">
          {rows.length} issue(s) previewed
          {run.report.truncated && " (first 500)"}
          {problems.length > 0 && ` · ${problems.length} would be skipped`}
        </span>
        {problems.length > 0 && (
          <label className="ml-auto flex items-center gap-1.5 text-xs text-fg-secondary">
            <input
              type="checkbox"
              checked={onlyProblems}
              onChange={(e) => setOnlyProblems(e.target.checked)}
            />
            Problems only
          </label>
        )}
      </div>
      <ul className="max-h-64 overflow-y-auto divide-y divide-subtle/60">
        {shown.map((row) => (
          <li key={row.jira_key} className="flex items-baseline gap-2 px-2.5 py-1 text-xs">
            <span className="w-16 shrink-0 font-mono text-fg-faint">{row.jira_key}</span>
            <span
              className={
                "w-14 shrink-0 " +
                (row.action === "skip"
                  ? "text-red-400"
                  : row.action === "update"
                    ? "text-amber-400"
                    : "text-emerald-400")
              }
            >
              {row.action}
            </span>
            <span className="w-20 shrink-0 font-mono text-fg-secondary">{row.radd_key}</span>
            <span className="truncate text-fg-secondary">{row.reason || row.title}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
