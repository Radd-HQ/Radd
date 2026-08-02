import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import { MOVE_JOB_POLL_MS, apiStorageHostMovePath } from "../../../lib/constants";
import { formatSize } from "../../../lib/attachments";
import { queryKeys, storageMoveJobQuery } from "../../../lib/queries";
import {
  MoveJobState,
  type MoveJobRead,
  type MoveJobStateValue,
  type StorageHostRead,
} from "../../../lib/types";
import { Button } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { Modal } from "../../Modal";
import { SelectField } from "../../SelectField";

const STATE_LABELS: Record<MoveJobStateValue, string> = {
  [MoveJobState.pending]: "Queued…",
  [MoveJobState.running]: "Moving…",
  [MoveJobState.done]: "Done",
  [MoveJobState.doneWithFailures]: "Done, with skips",
  [MoveJobState.failed]: "Failed",
  [MoveJobState.canceled]: "Canceled",
};

/** Card border + state text + progress-bar fill per outcome. */
const STATE_TONES: Record<MoveJobStateValue, { border: string; text: string; bar: string }> = {
  [MoveJobState.pending]: { border: "border-subtle", text: "text-fg-muted", bar: "bg-accent" },
  [MoveJobState.running]: { border: "border-subtle", text: "text-fg-muted", bar: "bg-accent" },
  [MoveJobState.done]: {
    border: "border-emerald-500/40",
    text: "text-emerald-300",
    bar: "bg-emerald-400",
  },
  [MoveJobState.doneWithFailures]: {
    border: "border-amber-500/40",
    text: "text-amber-300",
    bar: "bg-amber-400",
  },
  [MoveJobState.failed]: { border: "border-red-500/40", text: "text-red-400", bar: "bg-red-400" },
  [MoveJobState.canceled]: { border: "border-subtle", text: "text-fg-muted", bar: "bg-elevated" },
};

const isActive = (state: MoveJobStateValue) =>
  state === MoveJobState.pending || state === MoveJobState.running;

/**
 * Live progress for one host-to-host move (spec 102): polls every ~2s while
 * the job runs; a finished job reads green, amber ("Done, with skips" — the
 * skipped files listed) or red, and refreshes the host contents counts.
 */
export function MoveJobProgress({
  jobId,
  hosts,
}: {
  jobId: string;
  hosts: StorageHostRead[];
}) {
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState(false);
  const job = useQuery({
    ...storageMoveJobQuery(jobId),
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === undefined || isActive(state) ? MOVE_JOB_POLL_MS : false;
    },
  });

  // The moment the job settles, the hosts' contents columns are stale.
  const state = job.data?.state;
  useEffect(() => {
    if (state !== undefined && !isActive(state)) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageHosts });
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageMoveJobs });
    }
  }, [state, queryClient]);

  if (dismissed || !job.data) return null;
  const data = job.data;
  const tone = STATE_TONES[data.state];
  const settled = data.moved + data.failed;
  const fraction = data.total === 0 ? 1 : settled / data.total;
  const hostName = (id: string) => hosts.find((host) => host.id === id)?.name ?? "unknown host";

  return (
    <div className={`mt-3 rounded-lg border px-3 py-2.5 ${tone.border}`}>
      <div className="flex items-center gap-2 text-[13px]">
        <span className="font-medium text-heading">
          Moving {hostName(data.source_host_id)} → {hostName(data.target_host_id)}
        </span>
        <span className={`text-xs ${tone.text}`}>{STATE_LABELS[data.state]}</span>
        <span className="ml-auto text-xs text-fg-muted">
          {settled} / {data.total}
          {data.failed > 0 && ` · ${data.failed} skipped`}
        </span>
        {!isActive(data.state) && (
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label="Dismiss move report"
            className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
          >
            <X size={13} aria-hidden />
          </button>
        )}
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-elevated">
        <div
          className={`h-full rounded-full transition-all ${tone.bar}`}
          style={{ width: `${Math.round(fraction * 100)}%` }}
        />
      </div>
      {data.problems.length > 0 && (
        <ul className="mt-2 flex flex-col gap-0.5 text-xs text-amber-300">
          {data.problems.map((problem) => (
            <li key={problem.attachment_id} className="truncate">
              {problem.filename}: {problem.detail}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * "Move all to…" (spec 102): pick a target, confirm, start the job. The server
 * 409s a second concurrent move or a target equal to the source — the detail
 * surfaces inline.
 */
export function MoveHostDialog({
  source,
  hosts,
  onStarted,
  onClose,
}: {
  source: StorageHostRead;
  hosts: StorageHostRead[];
  onStarted: (jobId: string) => void;
  onClose: () => void;
}) {
  const [targetId, setTargetId] = useState("");
  const [confirmDialog, confirm] = useConfirm();
  const targets = hosts.filter((host) => host.id !== source.id);

  const start = useMutation({
    mutationFn: () =>
      api.post<MoveJobRead>(apiStorageHostMovePath(source.id), { target_host_id: targetId }),
    onSuccess: (jobData) => {
      onStarted(jobData.id);
      onClose();
    },
  });

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!targetId) return;
    const target = targets.find((host) => host.id === targetId);
    const ok = await confirm({
      title: "Move all attachments",
      message: `Move ${source.attachment_count} files (${formatSize(source.total_bytes)}) from "${source.name}" to "${target?.name}"? Each file is copied, verified, repointed, then removed from the source; downloads keep working throughout.`,
      confirmLabel: "Start move",
    });
    if (ok) start.mutate();
  };

  return (
    <Modal title={`Move all from ${source.name}`} onClose={onClose}>
      <form onSubmit={(event) => void onSubmit(event)} className="flex flex-col gap-3">
        <SelectField
          label="Target host"
          value={targetId}
          onChange={(event) => setTargetId(event.target.value)}
          hint="Every attachment on the source moves; the source ends up empty."
        >
          <option value="" disabled>
            Pick a host…
          </option>
          {targets.map((host) => (
            <option key={host.id} value={host.id}>
              {host.name}
            </option>
          ))}
        </SelectField>
        <div className="flex items-center justify-end gap-2">
          {start.isError && (
            <span className="mr-auto text-xs text-red-400">{errorMessage(start.error)}</span>
          )}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!targetId || start.isPending}>
            {start.isPending ? "Starting…" : "Move all"}
          </Button>
        </div>
      </form>
      {confirmDialog}
    </Modal>
  );
}
