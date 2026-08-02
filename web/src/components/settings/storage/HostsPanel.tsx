import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowRightLeft, HardDrive, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import {
  apiStorageHostDefaultPath,
  apiStorageHostHealthPath,
  apiStorageHostPath,
} from "../../../lib/constants";
import { formatSize } from "../../../lib/attachments";
import {
  instanceStatusQuery,
  queryKeys,
  storageHostsQuery,
  storageMoveJobsQuery,
} from "../../../lib/queries";
import {
  DeliveryMode,
  MoveJobState,
  StorageHostSource,
  StorageHostType,
  type StorageHostHealth,
  type StorageHostRead,
  type StorageHostTypeValue,
} from "../../../lib/types";
import { Button } from "../../Button";
import { useConfirm } from "../../ConfirmDialog";
import { DropdownMenu } from "../../DropdownMenu";
import { EmptyState } from "../../EmptyState";
import { QueryError } from "../../QueryError";
import { Table, TBody, Td, Th, THead } from "../../Table";
import { TableSkeleton } from "../../TableSkeleton";
import { HostDialog } from "./HostDialog";
import { MoveHostDialog, MoveJobProgress } from "./MoveJobProgress";

const TYPE_LABELS: Record<StorageHostTypeValue, string> = {
  [StorageHostType.filesystem]: "Filesystem",
  [StorageHostType.s3]: "S3",
};

const sectionHeadClasses = "mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted";

/**
 * The storage-host registry (spec 102): every place attachment bytes can live.
 * Counts/bytes come from the list endpoint; health is a live per-row probe.
 */
export function HostsPanel() {
  const hosts = useQuery(storageHostsQuery());
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const [editing, setEditing] = useState<StorageHostRead | null>(null);
  const [adding, setAdding] = useState(false);
  const [moving, setMoving] = useState<StorageHostRead | null>(null);
  // The job the progress card follows: one just started here, else one already
  // running when the page loaded (an admin may return mid-move).
  const [trackedJobId, setTrackedJobId] = useState<string | null>(null);
  const moveJobs = useQuery(storageMoveJobsQuery());
  const activeJobId =
    trackedJobId ??
    (moveJobs.data ?? []).find(
      (job) => job.state === MoveJobState.pending || job.state === MoveJobState.running,
    )?.id ??
    null;
  // Per-row probe outcome; "pending" while the request is in flight.
  const [checks, setChecks] = useState<Record<string, StorageHostHealth | "pending">>({});

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.storageHosts });
    // The Server page's "Attachment storage" pill reads the default host.
    void queryClient.invalidateQueries({ queryKey: instanceStatusQuery.queryKey });
  };

  const health = useMutation({
    mutationFn: (hostId: string) =>
      api.get<StorageHostHealth>(apiStorageHostHealthPath(hostId)),
    onMutate: (hostId) => setChecks((prev) => ({ ...prev, [hostId]: "pending" })),
    onSuccess: (result, hostId) => setChecks((prev) => ({ ...prev, [hostId]: result })),
    // The endpoint reports probe failures as data; an error here is Radd itself (403, network).
    onError: (error, hostId) =>
      setChecks((prev) => ({ ...prev, [hostId]: { ok: false, detail: errorMessage(error) } })),
  });

  const makeDefault = useMutation({
    mutationFn: (hostId: string) =>
      api.post<StorageHostRead>(apiStorageHostDefaultPath(hostId), {}),
    onSettled: invalidate,
  });

  const remove = useMutation({
    mutationFn: (hostId: string) => api.delete<void>(apiStorageHostPath(hostId)),
    onSettled: invalidate,
  });

  const onDelete = async (host: StorageHostRead) => {
    const ok = await confirm({
      title: "Delete storage host",
      message: `Delete "${host.name}"? Only an empty host can go — attachments still living there block deletion.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate(host.id);
  };

  const list = hosts.data ?? [];

  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className={`${sectionHeadClasses} mb-0`}>Hosts</h2>
        <Button onClick={() => setAdding(true)}>
          <Plus size={14} aria-hidden />
          Add host
        </Button>
      </div>
      <p className="mb-3 text-xs text-fg-muted">
        Filesystem roots and S3-compatible endpoints. Credentials are stored server-side and
        never shown again; use Check to probe a host live.
      </p>
      {hosts.isPending ? (
        <TableSkeleton rows={2} />
      ) : hosts.isError ? (
        <QueryError label="storage hosts" error={hosts.error} />
      ) : list.length === 0 ? (
        <EmptyState
          icon={HardDrive}
          message="No storage hosts — uploads have nowhere to land until one is added."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-subtle">
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                <Th>Type</Th>
                <Th>Location</Th>
                <Th>Delivery</Th>
                <Th>User-selectable</Th>
                <Th>Contents</Th>
                <Th>Health</Th>
                <Th className="w-10" />
              </tr>
            </THead>
            <TBody>
              {list.map((host) => (
                <HostRow
                  key={host.id}
                  host={host}
                  check={checks[host.id]}
                  onCheck={() => health.mutate(host.id)}
                  onEdit={() => setEditing(host)}
                  onMakeDefault={() => makeDefault.mutate(host.id)}
                  onMove={() => setMoving(host)}
                  onDelete={() => void onDelete(host)}
                />
              ))}
            </TBody>
          </Table>
        </div>
      )}
      {activeJobId && <MoveJobProgress jobId={activeJobId} hosts={list} />}
      {(remove.isError || makeDefault.isError) && (
        <p className="mt-2 text-xs text-red-400">
          {errorMessage(remove.error ?? makeDefault.error)}
        </p>
      )}
      {moving && (
        <MoveHostDialog
          source={moving}
          hosts={list}
          onStarted={setTrackedJobId}
          onClose={() => setMoving(null)}
        />
      )}
      {(adding || editing) && (
        <HostDialog
          existing={editing}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
        />
      )}
      {confirmDialog}
    </section>
  );
}

function HostRow({
  host,
  check,
  onCheck,
  onEdit,
  onMakeDefault,
  onMove,
  onDelete,
}: {
  host: StorageHostRead;
  check: StorageHostHealth | "pending" | undefined;
  onCheck: () => void;
  onEdit: () => void;
  onMakeDefault: () => void;
  onMove: () => void;
  onDelete: () => void;
}) {
  const location =
    host.host_type === StorageHostType.s3
      ? `${host.endpoint} / ${host.bucket}`
      : host.root_dir;
  const result = check && check !== "pending" ? check : null;

  return (
    <>
      <tr>
        <Td className="font-medium text-heading">
          <span className="inline-flex items-center gap-1.5">
            {host.name}
            {host.is_default && (
              <span
                className="rounded bg-accent/15 px-1.5 py-px text-[10px] font-normal text-accent-text"
                title="Every upload lands here until a routing rule says otherwise"
              >
                default
              </span>
            )}
            {host.source === StorageHostSource.env && (
              <span
                className="rounded bg-elevated px-1.5 py-px text-[10px] font-normal text-fg-muted"
                title="Seeded from environment variables — editable like any other row"
              >
                env
              </span>
            )}
          </span>
        </Td>
        <Td>{TYPE_LABELS[host.host_type]}</Td>
        <Td className="max-w-56 truncate" title={location}>
          {location || <span className="text-fg-faint">server default directory</span>}
        </Td>
        <Td>
          <span
            className={
              "rounded px-1.5 py-px text-[11px] " +
              (host.delivery_mode === DeliveryMode.presigned
                ? "bg-accent/15 text-accent-text"
                : "bg-elevated text-fg-secondary")
            }
            title={
              host.delivery_mode === DeliveryMode.presigned
                ? "Browsers fetch bytes straight from the host via a short presigned URL"
                : "Bytes stream through the Radd API"
            }
          >
            {host.delivery_mode}
          </span>
        </Td>
        <Td>{host.user_selectable ? "Yes" : <span className="text-fg-faint">—</span>}</Td>
        <Td className="whitespace-nowrap">
          {host.attachment_count === 0 ? (
            <span className="text-fg-faint">empty</span>
          ) : (
            `${host.attachment_count} · ${formatSize(host.total_bytes)}`
          )}
        </Td>
        <Td className="whitespace-nowrap">
          <span className="inline-flex items-center gap-1.5">
            {result && (
              <span
                className={
                  "inline-block size-2 rounded-full " +
                  (result.ok ? "bg-emerald-400" : "bg-red-400")
                }
                title={result.ok ? "Reachable" : result.detail}
              />
            )}
            <Button size="sm" variant="ghost" onClick={onCheck} disabled={check === "pending"}>
              <Activity size={13} aria-hidden />
              {check === "pending" ? "Checking…" : "Check"}
            </Button>
          </span>
        </Td>
        <Td>
          <DropdownMenu
            label={`Actions for ${host.name}`}
            align="end"
            items={[
              { kind: "action", label: "Edit", icon: Pencil, onSelect: onEdit },
              {
                kind: "action",
                label: "Make default",
                icon: Star,
                onSelect: onMakeDefault,
                disabled: host.is_default,
              },
              {
                kind: "action",
                label: "Move all to…",
                icon: ArrowRightLeft,
                onSelect: onMove,
                disabled: host.attachment_count === 0,
              },
              { kind: "separator" },
              { kind: "action", label: "Delete", icon: Trash2, danger: true, onSelect: onDelete },
            ]}
          />
        </Td>
      </tr>
      {result && !result.ok && (
        <tr>
          <Td colSpan={8} className="py-1.5">
            <span className="text-xs text-red-400">{result.detail}</span>
          </Td>
        </tr>
      )}
    </>
  );
}
