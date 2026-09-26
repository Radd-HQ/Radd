import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Link2 } from "lucide-react";
import { api, Button, EmptyState, ErrorText, QueryError, Table, TableSkeleton, TBody, Th, THead, useConfirm } from "@radd/plugin-sdk";
import { JiraPath, jiraKeys, pendingQuery, runsQuery } from "./api";
import { RunRow } from "./RunRow";
import type { JiraRun, PendingSummary, RollbackPreflight } from "./types";

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
  const runs = useQuery(runsQuery());
  const pending = useQuery(pendingQuery());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmNode, confirm] = useConfirm();
  // The newest run with problems opens by default — the thing you came to read.
  const autoOpen = (runs.data ?? []).find((r) => r.problems.length > 0)?.id ?? null;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: jiraKeys.runs });
    void queryClient.invalidateQueries({ queryKey: jiraKeys.pending });
  };

  const relink = useMutation({
    mutationFn: () => api.post<PendingSummary>(JiraPath.relink, {}),
    onSuccess: invalidate,
  });

  const rollback = useMutation({
    mutationFn: ({ id, includeSchema }: { id: string; includeSchema: boolean }) =>
      api.post<JiraRun>(`${JiraPath.runs}/${id}/rollback`, {
        include_schema: includeSchema,
        skip_edited: true,
      }),
    onSuccess: invalidate,
  });

  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`${JiraPath.runs}/${id}/cancel`, {}),
    onSuccess: invalidate,
  });

  const onRollback = async (run: JiraRun) => {
    const preflight = await api.get<RollbackPreflight>(`${JiraPath.runs}/${run.id}/rollback`);
    const edited = preflight.edited_since.length;
    const ok = await confirm({
      title: "Undo this import?",
      message: (
        <span>
          {preflight.total} row(s) would be undone.
          {edited > 0 && (
            <>
              {" "}
              <span className="text-status-warning-ink">
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

  const waiting = pending.data?.total ?? 0;
  return (
    <section className="rounded-lg border border-subtle bg-surface p-4" data-jira-section="runs">
      {confirmNode}
      <header className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-medium text-heading">Runs</h2>
          <p className="mt-0.5 text-xs text-fg-secondary">
            Dry runs, imports and rollbacks. Everything reads the local cache — no Jira needed.
          </p>
        </div>
        {waiting > 0 && (
          <Button
            size="sm"
            variant="secondary"
            className="shrink-0"
            onClick={() => relink.mutate()}
            disabled={relink.isPending}
            title="Retry every cross-project reference against what is imported now"
          >
            <Link2 size={13} /> Relink {waiting}
          </Button>
        )}
      </header>

      {waiting > 0 && (
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
        <ErrorText className="mt-2" error={rollback.error ?? relink.error} />
      )}
    </section>
  );
}
