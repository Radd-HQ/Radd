import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Database, Loader2, Trash2, X } from "lucide-react";
import { api, Button, EmptyState, QueryError, relativeTime, Table, TableSkeleton, TBody, Td, Th, THead, useConfirm } from "@radd/plugin-sdk";
import { JiraPath, jiraKeys, snapshotsQuery } from "./api";
import { NewDownloadModal } from "./NewDownloadModal";
import { ProblemList } from "./ProblemList";
import { SNAPSHOT_STAGE_LABELS, SnapshotStage, TERMINAL_SNAPSHOT_STAGES, type JiraSnapshot } from "./types";

const POLL_MS = 1500;

function bytes(size: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

const isRunning = (snapshot: JiraSnapshot) => !TERMINAL_SNAPSHOT_STAGES.includes(snapshot.stage);

/**
 * Cached Jira downloads (spec 100).
 *
 * A snapshot is downloaded ONCE and everything after it — profiling, mapping,
 * the dry run, the import, a re-import, relinking — reads the cache instead of
 * Jira. Spec 90 re-paged Jira on every run, so fixing one mapping mistake meant
 * downloading tens of thousands of issues again.
 *
 * Each row shows what it costs and has an X, because a cache nobody can clear
 * just accumulates.
 */
export function SnapshotsPanel() {
  const queryClient = useQueryClient();
  // Polls itself while a download is moving, and stops once they have all settled.
  const snapshots = useQuery(snapshotsQuery(POLL_MS));
  const [adding, setAdding] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmNode, confirm] = useConfirm();

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: jiraKeys.snapshots });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${JiraPath.snapshots}/${id}`),
    onSuccess: invalidate,
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`${JiraPath.snapshots}/${id}/cancel`, {}),
    onSuccess: invalidate,
  });

  const onDelete = async (snapshot: JiraSnapshot) => {
    const ok = await confirm({
      title: `Delete “${snapshot.name}”?`,
      message: `Frees ${bytes(snapshot.byte_size)}. Anything already imported from it stays — but re-importing from cache will need a fresh download.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(snapshot.id);
  };

  return (
    <section className="rounded-lg border border-subtle bg-surface p-4" data-jira-section="downloads">
      {confirmNode}
      <header className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-medium text-heading">Downloads</h2>
          <p className="mt-0.5 text-xs text-fg-secondary">
            Jira is read once into a local cache. Mapping, the dry run and the import all work from
            it, so you can fix a mistake and re-run without touching Jira again.
          </p>
        </div>
        <Button size="sm" className="shrink-0 whitespace-nowrap" onClick={() => setAdding(true)}>
          New download
        </Button>
      </header>

      {snapshots.isPending ? (
        <TableSkeleton rows={2} />
      ) : snapshots.isError ? (
        <QueryError label="Jira downloads" error={snapshots.error} />
      ) : snapshots.data.length === 0 ? (
        <EmptyState icon={Database} message="No downloads yet — start one to begin an import." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Download</Th>
                <Th>Issues</Th>
                <Th>Size</Th>
                <Th>Status</Th>
                <Th className="text-right">Actions</Th>
              </tr>
            </THead>
            <TBody>
              {snapshots.data.map((snapshot) => (
                <SnapshotRow
                  key={snapshot.id}
                  snapshot={snapshot}
                  expanded={expanded === snapshot.id}
                  onToggle={() => setExpanded((id) => (id === snapshot.id ? null : snapshot.id))}
                  onCancel={() => cancel.mutate(snapshot.id)}
                  onDelete={() => void onDelete(snapshot)}
                />
              ))}
            </TBody>
          </Table>
        </div>
      )}

      {adding && <NewDownloadModal onClose={() => setAdding(false)} onStarted={invalidate} />}
    </section>
  );
}

function SnapshotRow({
  snapshot,
  expanded,
  onToggle,
  onCancel,
  onDelete,
}: {
  snapshot: JiraSnapshot;
  expanded: boolean;
  onToggle: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const running = isRunning(snapshot);
  const total = snapshot.counts.issues_total ?? 0;
  const done = snapshot.counts.issues ?? 0;
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <>
      <tr>
        <Td>
          <button
            type="button"
            onClick={onToggle}
            className="text-left text-heading hover:text-accent-text cursor-pointer"
          >
            {snapshot.name}
          </button>
          <div className="mt-0.5 font-mono text-[11px] text-fg-faint">{snapshot.jql}</div>
        </Td>
        <Td className="whitespace-nowrap text-xs text-fg-secondary">
          {running && total > 0 ? `${done} / ${total}` : snapshot.issue_count}
        </Td>
        <Td className="whitespace-nowrap text-xs text-fg-secondary">
          {snapshot.byte_size ? bytes(snapshot.byte_size) : "—"}
        </Td>
        <Td>
          <StageCell snapshot={snapshot} percent={percent} />
        </Td>
        <Td>
          <div className="flex items-center justify-end gap-1">
            {running ? (
              <Button size="sm" variant="ghost" onClick={onCancel} title="Stop after the current page">
                <X size={13} /> Cancel
              </Button>
            ) : (
              <Button
                size="sm"
                variant="danger-ghost"
                aria-label={`Delete ${snapshot.name}`}
                title={`Delete — frees ${bytes(snapshot.byte_size)}`}
                onClick={onDelete}
              >
                <Trash2 size={13} />
              </Button>
            )}
          </div>
        </Td>
      </tr>
      {expanded && (
        <tr>
          <Td colSpan={5}>
            <SnapshotDetail snapshot={snapshot} />
          </Td>
        </tr>
      )}
    </>
  );
}

function StageCell({ snapshot, percent }: { snapshot: JiraSnapshot; percent: number }) {
  const label = SNAPSHOT_STAGE_LABELS[snapshot.stage] ?? snapshot.stage;
  if (snapshot.stage === SnapshotStage.done) {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-status-success-ink">
        <CheckCircle2 size={13} /> {label}
        <span className="text-fg-faint">· {relativeTime(snapshot.created_at)}</span>
      </span>
    );
  }
  if (snapshot.stage === SnapshotStage.failed || snapshot.stage === SnapshotStage.canceled) {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-status-danger-ink">
        <CircleAlert size={13} /> {label}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-fg-secondary">
      <Loader2 size={13} className="animate-spin" />
      {label}
      {percent > 0 && <span className="text-fg-faint">{percent}%</span>}
    </span>
  );
}

/** Counts worth surfacing, in the order they happen. */
const COUNT_LABELS: [string, string][] = [
  ["issues", "issues cached"],
  ["catalog_fields", "Jira fields catalogued"],
  ["comments_backfilled", "comments recovered from truncated lists"],
  ["worklogs_backfilled", "worklogs recovered from truncated lists"],
  ["history_backfilled", "history entries recovered"],
  ["attachments", "attachments downloaded"],
  ["page_retries", "page retries"],
];

function SnapshotDetail({ snapshot }: { snapshot: JiraSnapshot }) {
  const shown = COUNT_LABELS.filter(([key]) => (snapshot.counts[key] ?? 0) > 0);
  return (
    <div className="flex flex-col gap-2 py-1">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-secondary">
        {shown.map(([key, label]) => (
          <span key={key}>
            <span className="text-heading">{snapshot.counts[key]}</span> {label}
          </span>
        ))}
        {shown.length === 0 && <span className="text-fg-faint">Nothing cached yet.</span>}
      </div>
      <ProblemList problems={snapshot.problems} label="issue" />
    </div>
  );
}
