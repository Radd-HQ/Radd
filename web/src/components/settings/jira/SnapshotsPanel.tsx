import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Database, Loader2, Trash2, X } from "lucide-react";
import { api } from "../../../lib/api";
import { ApiPath } from "../../../lib/constants";
import { relativeTime } from "../../../lib/dates";
import {
  jiraConnectionsQuery,
  jiraProjectsQuery,
  jiraSnapshotsQuery,
  queryKeys,
} from "../../../lib/queries";
import {
  SNAPSHOT_STAGE_LABELS,
  SnapshotStage,
  TERMINAL_SNAPSHOT_STAGES,
  type JiraSnapshot,
  type SnapshotStartInput,
} from "../../../lib/types";
import { Button } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { EmptyState } from "../../EmptyState";
import { Modal } from "../../Modal";
import { QueryError } from "../../QueryError";
import { SelectField } from "../../SelectField";
import { Table, TBody, Td, THead, Th } from "../../Table";
import { TableSkeleton } from "../../TableSkeleton";
import { TextField } from "../../TextField";
import { ProblemList } from "./ProblemList";
import { ErrorText } from "../../ErrorText";

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

const isRunning = (snapshot: JiraSnapshot) =>
  !TERMINAL_SNAPSHOT_STAGES.includes(snapshot.stage);

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
export function SnapshotsPanel({
  onUse,
  selectedId,
}: {
  onUse?: (snapshot: JiraSnapshot) => void;
  selectedId?: string | null;
}) {
  const queryClient = useQueryClient();
  // Polls itself while a download is moving, and stops once they have all settled.
  const snapshots = useQuery(jiraSnapshotsQuery(POLL_MS));
  const [adding, setAdding] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmNode, confirm] = useConfirm();

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: queryKeys.jiraSnapshots });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${ApiPath.jiraSnapshots}/${id}`),
    onSuccess: invalidate,
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`${ApiPath.jiraSnapshots}/${id}/cancel`, {}),
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
    <section className="rounded-lg border border-subtle bg-surface p-4">
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
                  selected={selectedId === snapshot.id}
                  onToggle={() => setExpanded((id) => (id === snapshot.id ? null : snapshot.id))}
                  onUse={onUse}
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
  selected,
  onToggle,
  onUse,
  onCancel,
  onDelete,
}: {
  snapshot: JiraSnapshot;
  expanded: boolean;
  selected: boolean;
  onToggle: () => void;
  onUse?: (snapshot: JiraSnapshot) => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const running = isRunning(snapshot);
  const total = snapshot.counts.issues_total ?? 0;
  const done = snapshot.counts.issues ?? 0;
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <>
      <tr className={selected ? "bg-overlay" : undefined}>
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
            {onUse && snapshot.stage === SnapshotStage.done && (
              <Button size="sm" variant={selected ? "primary" : "secondary"} onClick={() => onUse(snapshot)}>
                {selected ? "Selected" : "Use"}
              </Button>
            )}
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
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-emerald-400">
        <CheckCircle2 size={13} /> {label}
        <span className="text-fg-faint">· {relativeTime(snapshot.created_at)}</span>
      </span>
    );
  }
  if (snapshot.stage === SnapshotStage.failed || snapshot.stage === SnapshotStage.canceled) {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap text-xs text-red-400">
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

function NewDownloadModal({
  onClose,
  onStarted,
}: {
  onClose: () => void;
  onStarted: () => void;
}) {
  const connections = useQuery(jiraConnectionsQuery());
  const [form, setForm] = useState<SnapshotStartInput>({
    name: "",
    jira_project_key: "",
    jql: "",
    connection_id: null,
    include_attachments: false,
    include_history: false,
  });
  const set = <K extends keyof SnapshotStartInput>(key: K, value: SnapshotStartInput[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const connectionId =
    form.connection_id ?? connections.data?.find((c) => c.is_default)?.id ?? null;
  const projects = useQuery(jiraProjectsQuery(connectionId, Boolean(connectionId)));

  const start = useMutation({
    mutationFn: () =>
      api.post<JiraSnapshot>(ApiPath.jiraSnapshots, { ...form, connection_id: connectionId }),
    onSuccess: () => {
      onStarted();
      onClose();
    },
  });

  const pickProject = (key: string) => {
    setForm((prev) => ({
      ...prev,
      jira_project_key: key,
      // Left un-ordered on purpose: the server appends `ORDER BY created ASC`
      // when the caller does not sort, because Jira pages by offset and an
      // unstable sort skips and repeats rows under a long download.
      jql: key ? `project = ${key}` : "",
    }));
  };

  return (
    <Modal title="Download a Jira project" onClose={onClose} wide>
      <div className="flex flex-col gap-3">
        {(connections.data?.length ?? 0) > 1 && (
          <SelectField
            label="Connection"
            value={connectionId ?? ""}
            onChange={(e) => set("connection_id", e.target.value || null)}
          >
            {connections.data?.map((connection) => (
              <option key={connection.id} value={connection.id}>
                {connection.name}
              </option>
            ))}
          </SelectField>
        )}

        <SelectField
          label="Project"
          value={form.jira_project_key}
          onChange={(e) => pickProject(e.target.value)}
          hint={
            projects.isPending && connectionId
              ? "Loading projects…"
              : `${projects.data?.length ?? 0} projects visible to this connection`
          }
        >
          <option value="">Pick a project…</option>
          {projects.data?.map((project) => (
            <option key={project.key} value={project.key}>
              {project.key} — {project.name}
            </option>
          ))}
        </SelectField>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="jql" className="text-xs font-medium text-fg-secondary">
            JQL
          </label>
          <textarea
            id="jql"
            rows={3}
            value={form.jql}
            onChange={(e) => set("jql", e.target.value)}
            placeholder='project = DEV AND created >= "2025-01-01"'
            className="rounded-md border border-strong bg-surface px-2.5 py-2 font-mono text-[12px] text-heading outline-none focus-visible:outline-2 focus-visible:outline-focus"
          />
          <p className="text-xs text-fg-faint">
            Narrow it to download less. Ordering is added automatically so paging stays stable.
          </p>
        </div>

        <TextField
          label="Name"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder={form.jira_project_key ? `${form.jira_project_key} · today` : "Optional"}
          hint="How this cached download is labelled."
        />

        <fieldset className="rounded-md border border-subtle p-2.5">
          <legend className="px-1 text-xs font-medium text-fg-secondary">Also download</legend>
          <label className="flex items-start gap-2 text-xs text-fg-secondary">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={form.include_attachments}
              onChange={(e) => set("include_attachments", e.target.checked)}
            />
            <span>
              Attachments
              <span className="block text-fg-faint">
                Files are usually the bulk of a project — this can take a while.
              </span>
            </span>
          </label>
          <label className="mt-2 flex items-start gap-2 text-xs text-fg-secondary">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={form.include_history}
              onChange={(e) => set("include_history", e.target.checked)}
            />
            <span>
              Change history
              <span className="block text-fg-faint">
                Gives imported issues a real activity trail and real cycle-time data, instead of
                every change appearing to have happened at import time.
              </span>
            </span>
          </label>
        </fieldset>

        {start.isError && <ErrorText error={start.error} />}

        <div className="mt-1 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => start.mutate()}
            disabled={!form.jira_project_key || !form.jql.trim() || start.isPending}
          >
            {start.isPending ? "Starting…" : "Start download"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
