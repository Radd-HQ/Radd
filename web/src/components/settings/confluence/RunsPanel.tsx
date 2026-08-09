import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Undo2, X } from "lucide-react";
import { Button, ButtonVariant } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { api } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import { confluenceRunsQuery, queryKeys } from "../../../lib/queries";
import {
  CONFLUENCE_COUNT_LABELS,
  CONFLUENCE_SECTION_LABELS,
  CONFLUENCE_STAGE_LABELS,
  CONFLUENCE_TERMINAL_STAGES,
  type ConfluenceProblem,
  type ConfluenceMappingSection,
  type ConfluenceRollbackPreflight,
} from "../../../lib/types";

/**
 * What happened, and how to undo it (spec 117).
 *
 * A problem carries the mapping that caused it, so the report offers
 * "Fix in Macros → drawio" rather than leaving somebody to guess which control
 * to go and change.
 */
export function RunsPanel({
  onFix,
}: {
  onFix: (section: ConfluenceMappingSection, key: string) => void;
}) {
  const client = useQueryClient();
  const [confirmNode, confirm] = useConfirm();
  const runs = useQuery(confluenceRunsQuery());

  const invalidate = () =>
    void client.invalidateQueries({ queryKey: queryKeys.confluenceRuns });

  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`${ApiPath.confluenceRuns}/${id}/cancel`, {}),
    onSuccess: invalidate,
  });

  const rollback = useMutation({
    mutationFn: (id: string) =>
      api.post(`${ApiPath.confluenceRuns}/${id}/rollback`, {}),
    onSuccess: invalidate,
  });

  const rows = runs.data ?? [];
  if (!rows.length) {
    return null;
  }

  return (
    <section className="rounded-xl border border-subtle bg-surface p-4">
      <h2 className="mb-3 text-sm font-semibold text-heading">Runs</h2>
      <ul className="divide-y divide-subtle">
        {rows.map((run) => {
          const terminal = CONFLUENCE_TERMINAL_STAGES.has(run.stage);
          const counts = Object.entries(run.counts).filter(([key]) => CONFLUENCE_COUNT_LABELS[key]);
          return (
            <li key={run.id} className="py-3">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-medium text-heading">
                    {run.dry_run ? "Dry run" : "Import"} ·{" "}
                    <span className="font-normal text-fg-secondary">
                      {CONFLUENCE_STAGE_LABELS[run.stage] ?? run.stage}
                    </span>
                  </p>
                  {counts.length > 0 && (
                    <p className="mt-0.5 text-[12px] text-fg-muted">
                      {counts.map(([key, value]) => `${CONFLUENCE_COUNT_LABELS[key]}: ${value}`).join(" · ")}
                    </p>
                  )}
                </div>
                {!terminal && (
                  <Button
                    variant={ButtonVariant.ghost}
                    size="sm"
                    onClick={() => cancel.mutate(run.id)}
                  >
                    <X className="size-4" aria-hidden /> Cancel
                  </Button>
                )}
                {terminal && !run.dry_run && (
                  <Button
                    variant={ButtonVariant.ghost}
                    size="sm"
                    onClick={async () => {
                      const preflight = await api.get<ConfluenceRollbackPreflight>(
                        `${ApiPath.confluenceRuns}/${run.id}/rollback`,
                      );
                      if (
                        await confirm({
                          title: "Undo this import?",
                          message:
                            `${preflight.total} record(s) will be reversed.` +
                            (preflight.edited_since > 0
                              ? ` ${preflight.edited_since} page(s) have been edited since and will be left alone.`
                              : ""),
                          confirmLabel: "Undo",
                          danger: true,
                        })
                      ) {
                        rollback.mutate(run.id);
                      }
                    }}
                  >
                    <Undo2 className="size-4" aria-hidden /> Undo
                  </Button>
                )}
              </div>
              {run.problems.length > 0 && <ProblemList problems={run.problems} onFix={onFix} />}
            </li>
          );
        })}
      </ul>
      {confirmNode}
    </section>
  );
}

/** Grouped, because one bad macro produces the same problem on 200 pages. */
function ProblemList({
  problems,
  onFix,
}: {
  problems: ConfluenceProblem[];
  onFix: (section: ConfluenceMappingSection, key: string) => void;
}) {
  const grouped = new Map<string, { problem: ConfluenceProblem; count: number }>();
  for (const problem of problems) {
    const key = `${problem.kind}|${problem.section ?? ""}|${problem.mapping_key}`;
    const existing = grouped.get(key);
    if (existing) existing.count += 1;
    else grouped.set(key, { problem, count: 1 });
  }

  return (
    <ul className="mt-2 space-y-1">
      {[...grouped.values()].map(({ problem, count }, index) => (
        <li
          key={index}
          className="flex items-start justify-between gap-3 rounded-lg border border-subtle bg-elevated px-3 py-1.5 text-[12px]"
        >
          <span className="min-w-0 text-fg-secondary">
            {problem.message}
            {count > 1 && <span className="text-fg-faint"> ×{count}</span>}
          </span>
          {problem.section && problem.mapping_key && (
            <button
              type="button"
              className="shrink-0 font-medium text-accent-text hover:underline"
              onClick={() => onFix(problem.section as ConfluenceMappingSection, problem.mapping_key)}
            >
              Fix in {CONFLUENCE_SECTION_LABELS[problem.section]} → {problem.mapping_key}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
