import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Download, HardDriveDownload, RotateCcw, ShieldCheck, Trash2, Upload } from "lucide-react";
import { api, ApiError } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import { useListFilter } from "../../lib/list-filter";
import {
  backupRunQuery,
  backupSchedulesQuery,
  backupStatusQuery,
  backupsQuery,
  queryKeys,
} from "../../lib/queries";
import {
  BACKUP_KIND_LABELS,
  RUN_STAGE_LABELS,
  type BackupArtifact,
  type BackupSchedule,
  type BackupStatus,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ListSearchInput } from "../../components/ListSearchInput";
import { Modal } from "../../components/Modal";
import { QueryError } from "../../components/QueryError";
import { Table, TBody, Td, THead, Th } from "../../components/Table";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { useConfirm } from "../../components/ConfirmDialog";
import { formatDateTime } from "../../lib/dates";
import { ScheduleEditor, isScheduleValid } from "../../components/ScheduleEditor";
import { ScheduleKind, type RuleSchedule } from "../../lib/types";

const POLL_MS = 2000;

function bytes(size: number | null): string {
  if (size === null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

function when(iso: string | null): string {
  return iso ? formatDateTime(iso) : "—";
}

/** Human summary of a stored schedule config. */
function scheduleSummary(schedule: BackupSchedule): string {
  const { kind, minutes, time, weekdays, day, expression } = schedule.config as RuleSchedule;
  if (kind === ScheduleKind.interval) return `Every ${minutes} minutes`;
  if (kind === ScheduleKind.daily) return `Daily at ${time}`;
  if (kind === ScheduleKind.cron) return `Cron: ${expression}`;
  if (kind === ScheduleKind.monthly) return `Monthly on day ${day} at ${time}`;
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const named = (weekdays ?? []).map((d) => days[d]).join(", ");
  return `${named} at ${time}`;
}

/**
 * Settings → Backups (spec 99). Instance admin only; a 403 degrades to a notice.
 *
 * Three cards: status (where a broken deploy becomes visible), schedules, and
 * the artifact inventory — which the server reads from DISK, not a table, so a
 * restore cannot roll its own listing back.
 */
export function BackupsSettingsPage() {
  const [runId, setRunId] = useState<string | null>(null);
  const client = useQueryClient();
  const status = useQuery({
    ...backupStatusQuery(),
    // Poll while a run is in flight — `maintenance: false` is the honest
    // completion signal for a restore, since the run row itself does not
    // survive being restored over.
    refetchInterval: runId ? POLL_MS : false,
  });
  const run = useQuery({ ...backupRunQuery(runId), refetchInterval: runId ? POLL_MS : false });

  const finished = run.data && run.data.status !== "running" && run.data.status !== "pending";
  const restoreDone = runId !== null && run.isError && status.data?.maintenance === false;
  useEffect(() => {
    if (!finished && !restoreDone) return;
    setRunId(null);
    void client.invalidateQueries({ queryKey: queryKeys.backups() });
    void client.invalidateQueries({ queryKey: queryKeys.backupSchedules() });
  }, [finished, restoreDone, client]);

  const forbidden = status.error instanceof ApiError && status.error.status === 403;
  if (forbidden) {
    return (
      <SettingsPage title="Backups" description="Scheduled snapshots, restore, and the key that protects them.">
        <p className="rounded-md border border-subtle px-4 py-3 text-sm text-fg-muted">
          You need instance admin access to manage backups.
        </p>
      </SettingsPage>
    );
  }

  return (
    <SettingsPage
      title="Backups"
      description="Scheduled snapshots of the database and attachments, encrypted at rest."
      info={
        <>
          Backups are written to the directory below and encrypted with a key stored{" "}
          <strong>outside</strong> it. <strong>Back that key file up separately</strong> — without
          it, no backup can be restored.
        </>
      }
    >
      {status.isPending ? (
        <TableSkeleton rows={3} />
      ) : status.isError ? (
        <QueryError label="backup status" error={status.error} />
      ) : (
        <div className="flex flex-col gap-6">
          <StatusCard status={status.data} />
          {runId && run.data && <RunBanner stage={run.data.stage} kind={run.data.kind} />}
          <SchedulesCard />
          <ArtifactsCard status={status.data} runId={runId} onRun={setRunId} />
        </div>
      )}
    </SettingsPage>
  );
}

// --- status ---

function StatusCard({ status }: { status: BackupStatus }) {
  const problems = [status.directory_problem, status.tools_problem, status.key_problem].filter(
    Boolean,
  ) as string[];
  return (
    <section className="rounded-lg border border-subtle bg-surface p-4">
      <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Directory" value={status.directory} mono />
        <Fact
          label="Free space"
          value={status.directory_writable ? bytes(status.free_bytes) : "not writable"}
        />
        <Fact label="Next scheduled run" value={when(status.next_run_at)} />
        <Fact
          label="Encryption"
          value={
            status.encryption_enabled
              ? `AES-256-GCM · key ${status.key_id ?? "?"}`
              : "disabled"
          }
        />
        <Fact label="Key file" value={status.key_file} mono />
        <Fact
          label="Tools"
          value={`pg_dump ${status.pg_dump.version ?? "missing"} · pg_restore ${
            status.pg_restore.version ?? "missing"
          }`}
        />
      </div>
      {problems.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 border-t border-subtle pt-3">
          {problems.map((problem) => (
            <li key={problem} className="text-[13px] text-danger-text">
              {problem}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-wide text-fg-faint">{label}</div>
      <div className={`truncate text-[13px] text-fg ${mono ? "font-mono" : ""}`} title={value}>
        {value}
      </div>
    </div>
  );
}

function RunBanner({ stage, kind }: { stage: string; kind: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-accent/25 bg-accent/5 px-4 py-3">
      <span className="size-2 shrink-0 animate-pulse rounded-full bg-accent" aria-hidden />
      <span className="text-[13px] text-fg">
        {kind === "restore" ? "Restoring" : "Backing up"} — {RUN_STAGE_LABELS[stage as string] ?? stage}…
      </span>
    </div>
  );
}

// --- schedules ---

function SchedulesCard() {
  const schedules = useQuery(backupSchedulesQuery());
  const client = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [editing, setEditing] = useState<BackupSchedule | null>(null);
  const [creating, setCreating] = useState(false);

  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(`${ApiPath.backups}/schedules/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.backupSchedules() }),
  });
  const toggle = useMutation({
    mutationFn: (schedule: BackupSchedule) =>
      api.patch<BackupSchedule>(`${ApiPath.backups}/schedules/${schedule.id}`, {
        enabled: !schedule.enabled,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.backupSchedules() }),
  });

  return (
    <section>
      <header className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-heading">Schedules</h3>
        <Button size="sm" variant="secondary" onClick={() => setCreating(true)}>
          Add schedule
        </Button>
      </header>
      {schedules.isPending ? (
        <TableSkeleton rows={2} />
      ) : schedules.isError ? (
        <QueryError label="backup schedules" error={schedules.error} />
      ) : schedules.data.length === 0 ? (
        <EmptyState icon={Archive} message="No schedules — backups only run on demand." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                <Th>When</Th>
                <Th>Keep</Th>
                <Th>Attachments</Th>
                <Th>Last run</Th>
                <Th>Next run</Th>
                <Th />
              </tr>
            </THead>
            <TBody>
              {schedules.data.map((schedule) => (
                <tr key={schedule.id} className={schedule.enabled ? "" : "opacity-55"}>
                  <Td className="font-medium text-fg">{schedule.name}</Td>
                  <Td>{scheduleSummary(schedule)}</Td>
                  <Td>
                    {schedule.keep_last ? `${schedule.keep_last} newest` : ""}
                    {schedule.keep_last && schedule.keep_days ? ", " : ""}
                    {schedule.keep_days ? `${schedule.keep_days} days` : ""}
                    {!schedule.keep_last && !schedule.keep_days ? "everything" : ""}
                  </Td>
                  <Td>{schedule.include_attachments ? "included" : "no"}</Td>
                  <Td className="whitespace-nowrap">
                    {when(schedule.last_run_at)}
                    {schedule.last_status === "failed" && (
                      <span className="ml-2 text-danger-text" title={schedule.last_error ?? ""}>
                        failed
                      </span>
                    )}
                  </Td>
                  <Td className="whitespace-nowrap">
                    {schedule.enabled ? when(schedule.next_run_at) : "disabled"}
                  </Td>
                  <Td className="text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" onClick={() => toggle.mutate(schedule)}>
                      {schedule.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(schedule)}>
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        if (
                          await confirm({
                            title: `Delete “${schedule.name}”?`,
                            message: "Existing backups are kept; only the schedule is removed.",
                            confirmLabel: "Delete",
                            danger: true,
                          })
                        )
                          remove.mutate(schedule.id);
                      }}
                    >
                      <Trash2 size={14} aria-hidden />
                    </Button>
                  </Td>
                </tr>
              ))}
            </TBody>
          </Table>
        </div>
      )}
      {confirmDialog}
      {(creating || editing) && (
        <ScheduleModal
          schedule={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
    </section>
  );
}

function ScheduleModal({
  schedule,
  onClose,
}: {
  schedule: BackupSchedule | null;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState(schedule?.name ?? "Nightly");
  // The shared editor (RADD-912). This form used to hardcode "daily", so
  // monthly and cron were accepted by the API and unreachable in the product.
  const [config, setConfig] = useState<RuleSchedule>(
    (schedule?.config as RuleSchedule) ?? { kind: ScheduleKind.daily, time: "03:00" },
  );
  const [keepLast, setKeepLast] = useState(String(schedule?.keep_last ?? 7));
  const [attachments, setAttachments] = useState(schedule?.include_attachments ?? true);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        config,
        include_attachments: attachments,
        keep_last: Number(keepLast) || 1,
      };
      return schedule
        ? api.patch<BackupSchedule>(`${ApiPath.backups}/schedules/${schedule.id}`, body)
        : api.post<BackupSchedule>(`${ApiPath.backups}/schedules`, body);
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.backupSchedules() });
      onClose();
    },
  });

  return (
    <Modal onClose={onClose} title={schedule ? "Edit schedule" : "Add schedule"}>
      <div className="flex flex-col gap-4">
        <TextField label="Name" value={name} onChange={(event) => setName(event.target.value)} />
        <ScheduleEditor value={config} onChange={setConfig} />
        <TextField
          label="Keep newest"
          type="number"
          value={keepLast}
          onChange={(event) => setKeepLast(event.target.value)}
        />
        <label className="flex items-center gap-2 text-[13px] text-fg">
          <input
            type="checkbox"
            checked={attachments}
            onChange={(event) => setAttachments(event.target.checked)}
            className="accent-accent"
          />
          Include attachments
        </label>
        {save.isError && <QueryError label="schedule" error={save.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={save.isPending || !isScheduleValid(config)}
          >
            {schedule ? "Save" : "Create"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// --- artifacts ---

function ArtifactsCard({
  status,
  runId,
  onRun,
}: {
  status: BackupStatus;
  runId: string | null;
  onRun: (id: string) => void;
}) {
  const backups = useQuery(backupsQuery());
  const client = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const uploadRef = useRef<HTMLInputElement>(null);
  const [restoring, setRestoring] = useState<BackupArtifact | null>(null);

  const create = useMutation({
    mutationFn: () => api.post<{ id: string }>(ApiPath.backups, {}),
    onSuccess: (run) => onRun(run.id),
  });
  const remove = useMutation({
    mutationFn: (name: string) => api.delete<void>(`${ApiPath.backups}/${name}`),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.backups() }),
  });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(`/api/v1${ApiPath.backups}/upload`, {
        method: "POST",
        body,
        credentials: "include",
      });
      if (!response.ok) throw new ApiError(response.status, (await response.json()).detail);
      return response.json();
    },
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.backups() }),
  });

  const busy = runId !== null || create.isPending;
  const all = backups.data ?? [];
  const search = useListFilter(all, (backup) => [backup.name]);
  const list = search.filtered;

  return (
    <section>
      <header className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-heading">Available backups</h3>
        <div className="flex items-center gap-2">
          <input
            ref={uploadRef}
            type="file"
            accept=".radd"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate(file);
              event.target.value = "";
            }}
          />
          <Button
            size="sm"
            variant="secondary"
            onClick={() => uploadRef.current?.click()}
            disabled={upload.isPending || !status.directory_writable}
          >
            <Upload size={14} aria-hidden /> Upload
          </Button>
          <Button
            size="sm"
            onClick={() => create.mutate()}
            disabled={busy || !status.directory_writable || Boolean(status.tools_problem)}
          >
            <HardDriveDownload size={14} aria-hidden /> Back up now
          </Button>
        </div>
      </header>
      {upload.isError && <QueryError label="upload" error={upload.error} />}
      {create.isError && <QueryError label="backup" error={create.error} />}
      {backups.isPending ? (
        <TableSkeleton rows={3} />
      ) : backups.isError ? (
        <QueryError label="backups" error={backups.error} />
      ) : all.length === 0 ? (
        <EmptyState icon={Archive} message="No backups yet — take one now or wait for the schedule." />
      ) : (
        <>
          {all.length > 8 && (
            <ListSearchInput
              className="mb-3"
              value={search.filter}
              onChange={search.setFilter}
              placeholder="Filter backups by name…"
              total={all.length}
              matched={list.length}
              noun="backups"
            />
          )}
          {list.length === 0 ? (
            <EmptyState icon={Archive} message={`No backups match “${search.filter.trim()}”.`} />
          ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Taken</Th>
                <Th>Kind</Th>
                <Th>Size</Th>
                <Th>Contents</Th>
                <Th>By</Th>
                <Th />
              </tr>
            </THead>
            <TBody>
              {list.map((backup) => (
                <tr key={backup.name}>
                  <Td className="whitespace-nowrap">
                    <div className="text-fg">{when(backup.created_at)}</div>
                    <div className="font-mono text-[11px] text-fg-faint">{backup.name}</div>
                  </Td>
                  <Td>{BACKUP_KIND_LABELS[backup.kind] ?? backup.kind}</Td>
                  <Td className="whitespace-nowrap">{bytes(backup.size_bytes)}</Td>
                  <Td className="whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      {backup.encrypted && (
                        <ShieldCheck size={13} className="text-accent-text" aria-label="Encrypted" />
                      )}
                      database{backup.includes_attachments ? " + attachments" : ""}
                    </span>
                    {backup.problem && (
                      <div className="text-[11px] text-danger-text">{backup.problem}</div>
                    )}
                  </Td>
                  <Td className="truncate">{backup.created_by ?? "—"}</Td>
                  <Td className="text-right whitespace-nowrap">
                    <a
                      href={`/api/v1${ApiPath.backups}/${backup.name}/download`}
                      className="inline-flex items-center rounded p-1.5 text-fg-muted hover:bg-elevated hover:text-fg"
                      title="Download"
                    >
                      <Download size={14} aria-hidden />
                    </a>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={!backup.restorable || busy}
                      title={backup.problem ?? "Restore this backup"}
                      onClick={() => setRestoring(backup)}
                    >
                      <RotateCcw size={14} aria-hidden />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        if (
                          await confirm({
                            title: "Delete this backup?",
                            message: `${backup.name} will be removed from disk. This cannot be undone.`,
                            confirmLabel: "Delete",
                            danger: true,
                          })
                        )
                          remove.mutate(backup.name);
                      }}
                    >
                      <Trash2 size={14} aria-hidden />
                    </Button>
                  </Td>
                </tr>
              ))}
            </TBody>
          </Table>
        </div>
          )}
        </>
      )}
      {confirmDialog}
      {restoring && (
        <RestoreModal
          backup={restoring}
          onClose={() => setRestoring(null)}
          onStarted={(id) => {
            setRestoring(null);
            onRun(id);
          }}
        />
      )}
    </section>
  );
}

/**
 * Restore confirmation. Typing the database name is the guard — the same one the
 * CLI prompts for — because this replaces every row in the instance.
 */
function RestoreModal({
  backup,
  onClose,
  onStarted,
}: {
  backup: BackupArtifact;
  onClose: () => void;
  onStarted: (runId: string) => void;
}) {
  const [confirmText, setConfirmText] = useState("");
  const start = useMutation({
    mutationFn: () =>
      api.post<{ id: string }>(`${ApiPath.backups}/${backup.name}/restore`, {
        confirm: confirmText,
      }),
    onSuccess: (run) => onStarted(run.id),
  });

  return (
    <Modal onClose={onClose} title="Restore this backup?">
      <div className="flex flex-col gap-4">
        <div className="rounded-md border border-danger/30 bg-danger/5 px-3.5 py-3 text-[13px] text-fg">
          Every row in this instance will be <strong>replaced</strong> with the contents of this
          backup. A safety backup is taken first, and Radd is unavailable while it runs.
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
          <dt className="text-fg-muted">Taken</dt>
          <dd className="text-fg">{when(backup.created_at)}</dd>
          <dt className="text-fg-muted">By</dt>
          <dd className="text-fg">{backup.created_by ?? "—"}</dd>
          <dt className="text-fg-muted">Contents</dt>
          <dd className="text-fg">
            database{backup.includes_attachments ? " + attachments" : " only"}
          </dd>
          <dt className="text-fg-muted">Schema</dt>
          <dd className="text-fg">v{backup.schema_version ?? "?"}</dd>
        </dl>
        <TextField
          label="Type the database name to confirm"
          value={confirmText}
          onChange={(event) => setConfirmText(event.target.value)}
        />
        {start.isError && <QueryError label="restore" error={start.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={!confirmText || start.isPending}
            onClick={() => start.mutate()}
          >
            Restore
          </Button>
        </div>
      </div>
    </Modal>
  );
}
