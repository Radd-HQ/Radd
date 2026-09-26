import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Trash2, X } from "lucide-react";
import { api, useConfirm, Button, ButtonVariant, QueryError } from "@radd/plugin-sdk";
import { DownloadModal } from "./DownloadModal";
import { ConfluencePath, confluenceKeys, snapshotsQuery } from "./queries";
import {
  CONFLUENCE_COUNT_LABELS,
  CONFLUENCE_STAGE_LABELS,
  CONFLUENCE_TERMINAL_STAGES,
  type ConfluenceSnapshot,
} from "./types";

/**
 * The cache (spec 117). A selection is downloaded ONCE and every later step reads
 * it — which is what makes "fix a mapping and try again" a loop rather than
 * another download.
 */
export function SnapshotsPanel({
  onPlanFrom,
}: {
  onPlanFrom: (snapshot: ConfluenceSnapshot) => void;
}) {
  const client = useQueryClient();
  const [confirmNode, confirm] = useConfirm();
  const [starting, setStarting] = useState(false);
  const snapshots = useQuery(snapshotsQuery());

  const invalidate = () =>
    void client.invalidateQueries({ queryKey: confluenceKeys.snapshots });

  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`${ConfluencePath.snapshots}/${id}/cancel`, {}),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${ConfluencePath.snapshots}/${id}`),
    onSuccess: invalidate,
  });

  const rows = snapshots.data ?? [];

  return (
    <section className="rounded-xl border border-subtle bg-surface p-4" data-confluence-downloads>
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-heading">Downloads</h2>
          <p className="text-[13px] text-fg-muted">
            A whole space, a section and everything under it, or a set of pages.
          </p>
        </div>
        <Button size="sm" onClick={() => setStarting(true)}>
          <Download className="size-4" aria-hidden /> Download
        </Button>
      </header>

      {(cancel.isError || remove.isError) && <QueryError label="download action" error={cancel.error ?? remove.error}/>}
      {snapshots.isError ? <QueryError label="downloads" error={snapshots.error}/> : snapshots.isPending ? <p>Loading downloads…</p> : rows.length === 0 ? (
        <p className="text-[13px] text-fg-faint">Nothing downloaded yet.</p>
      ) : (
        <ul className="divide-y divide-subtle">
          {rows.map((snapshot) => {
            const terminal = CONFLUENCE_TERMINAL_STAGES.has(snapshot.stage);
            return (
              <li key={snapshot.id} className="flex items-center gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-heading">
                    {snapshot.name}
                  </p>
                  <p className="truncate text-[12px] text-fg-muted">
                    {CONFLUENCE_STAGE_LABELS[snapshot.stage] ?? snapshot.stage}
                    {snapshot.page_count > 0 && ` · ${snapshot.page_count} pages`}
                    {snapshot.include_history && " · with history"}
                    {snapshot.problems.length > 0 &&
                      ` · ${snapshot.problems.length} problem(s)`}
                  </p>
                  {!terminal && (
                    <p className="mt-1 text-[12px] text-fg-faint">
                      {Object.entries(snapshot.counts)
                        .filter(([key]) => CONFLUENCE_COUNT_LABELS[key])
                        .map(([key, value]) => `${CONFLUENCE_COUNT_LABELS[key]}: ${value}`)
                        .join(" · ")}
                    </p>
                  )}
                  {/* A bare "failed" is not a report. The reason is already on the
                      row — showing it is the difference between "something broke"
                      and knowing which page and why. */}
                  {snapshot.problems.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {snapshot.problems.slice(0, 3).map((problem, index) => (
                        <li key={index} className="text-[12px] text-fg-secondary">
                          {problem.message}
                          {problem.detail && (
                            <span className="text-fg-faint"> — {problem.detail}</span>
                          )}
                        </li>
                      ))}
                      {snapshot.problems.length > 3 && (
                        <li className="text-[12px] text-fg-faint">
                          …and {snapshot.problems.length - 3} more
                        </li>
                      )}
                    </ul>
                  )}
                </div>
                {snapshot.stage === "done" && (
                  <Button size="sm" onClick={() => onPlanFrom(snapshot)}>
                    Plan
                  </Button>
                )}
                {!terminal && (
                  <Button
                    variant={ButtonVariant.ghost}
                    size="sm"
                    onClick={() => cancel.mutate(snapshot.id)}
                  >
                    <X className="size-4" aria-hidden /> Cancel
                  </Button>
                )}
                <Button
                  variant={ButtonVariant.ghost}
                  size="sm"
                  aria-label={`Delete ${snapshot.name}`}
                  onClick={async () => {
                    if (
                      await confirm({
                        title: `Delete ${snapshot.name}?`,
                        message: "The cached pages and their downloaded files are removed. Anything already imported stays.",
                        confirmLabel: "Delete",
                        danger: true,
                      })
                    ) {
                      remove.mutate(snapshot.id);
                    }
                  }}
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
      )}

      {starting && <DownloadModal onClose={() => setStarting(false)} onStarted={invalidate} />}
      {confirmNode}
    </section>
  );
}
