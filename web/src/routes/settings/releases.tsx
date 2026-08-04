import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Pencil, Plus, Rocket, Trash2, X } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { ApiPath, apiReleasePath } from "../../lib/constants";
import { usePermissions } from "../../lib/hooks";
import { RELEASE_STATUS_META } from "../../lib/meta";
import { projectsQuery, queryKeys, releasesQuery } from "../../lib/queries";
import {
  Permission,
  ReleaseStatus,
  type Release,
  type ReleaseCreate,
  type ReleaseUpdate,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Modal } from "../../components/Modal";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";

/**
 * Per-project releases (spec 50). The project is supplied by the URL context
 * (`projectId`) rather than an in-page picker; gating is on THAT project.
 */
export function ReleasesSettingsPage({ projectId }: { projectId?: string }) {
  const perms = usePermissions();
  const projects = useQuery(projectsQuery());
  const [modal, setModal] = useState<{ release: Release | null } | null>(null);

  const project = (projects.data ?? []).find((entry) => entry.id === projectId);
  // Releases are per-project: gate on THAT project's manage permission.
  const canManage = perms.project(project, Permission.releaseUpdate);
  const releases = useQuery({ ...releasesQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const list = releases.data ?? [];

  return (
    <SettingsPage
      title="Releases"
      description="Versions items can target. Mark a release as released when it ships."
      actions={
        canManage && project ? (
          <Button onClick={() => setModal({ release: null })} className="self-end">
            <Plus size={14} aria-hidden />
            New release
          </Button>
        ) : undefined
      }
    >
      {projects.isPending || (projectId && releases.isPending) ? (
        <TableSkeleton rows={4} />
      ) : !project ? (
        <EmptyState icon={Rocket} message="Project not found." />
      ) : releases.isError ? (
        <QueryError label="releases" error={releases.error} />
      ) : list.length === 0 ? (
        <EmptyState
          icon={Rocket}
          message={canManage ? "No releases yet — create one to plan a version." : "No releases yet."}
        />
      ) : (
        <ul className="rounded-lg border border-subtle">
          {list.map((release) => (
            <ReleaseRow
              key={release.id}
              release={release}
              projectId={project.id}
              canManage={canManage}
              onEdit={() => setModal({ release })}
            />
          ))}
        </ul>
      )}

      {modal && project && (
        <ReleaseModal
          projectId={project.id}
          release={modal.release}
          onClose={() => setModal(null)}
        />
      )}
    </SettingsPage>
  );
}

function ReleaseRow({
  release,
  projectId,
  canManage,
  onEdit,
}: {
  release: Release;
  projectId: string;
  canManage: boolean;
  onEdit: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const status = RELEASE_STATUS_META[release.status];
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.releases(projectId) });

  const markReleased = useMutation({
    mutationFn: () =>
      api.patch<Release>(apiReleasePath(release.id), {
        status: ReleaseStatus.released,
      } satisfies ReleaseUpdate),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiReleasePath(release.id)),
    onSuccess: invalidate,
  });

  return (
    <li className="flex items-center gap-3 border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
      <span className={`size-2 shrink-0 rounded-full ${status.dotClassName}`} aria-hidden />
      <span className="font-mono text-[13px] text-heading">{release.version}</span>
      <span className="truncate text-[13px] text-fg-secondary">{release.name}</span>
      <span className="rounded border border-strong px-1.5 py-px text-[10px] uppercase tracking-wide text-fg-secondary">
        {status.label}
      </span>
      <span className="ml-auto shrink-0 text-xs text-fg-muted">
        {release.released_at
          ? `Released ${new Date(release.released_at).toLocaleDateString()}`
          : "—"}
      </span>
      {canManage &&
        (confirming ? (
          <span className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              className="rounded px-1.5 py-0.5 text-xs text-red-400 hover:bg-elevated cursor-pointer disabled:opacity-50"
            >
              {remove.isPending ? "Deleting…" : "Delete"}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              aria-label="Cancel delete"
              className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
            >
              <X size={13} />
            </button>
          </span>
        ) : (
          <>
            {release.status === ReleaseStatus.planned && (
              <button
                type="button"
                onClick={() => markReleased.mutate()}
                disabled={markReleased.isPending}
                className="inline-flex items-center gap-1 rounded border border-strong px-1.5 py-0.5 text-[11px] text-fg hover:bg-elevated hover:text-emerald-300 cursor-pointer disabled:opacity-50"
              >
                <CheckCircle2 size={12} aria-hidden />
                {markReleased.isPending ? "Releasing…" : "Mark released"}
              </button>
            )}
            <button
              type="button"
              onClick={onEdit}
              aria-label={`Edit ${release.version}`}
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
            >
              <Pencil size={13} />
            </button>
            <button
              type="button"
              onClick={() => setConfirming(true)}
              aria-label={`Delete ${release.version}`}
              className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
            >
              <Trash2 size={13} />
            </button>
          </>
        ))}
      {(markReleased.isError || remove.isError) && (
        <span className="text-xs text-red-400">
          {errorMessage(markReleased.error ?? remove.error)}
        </span>
      )}
    </li>
  );
}

function ReleaseModal({
  projectId,
  release,
  onClose,
}: {
  projectId: string;
  release: Release | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const editing = Boolean(release);
  const [name, setName] = useState(release?.name ?? "");
  const [version, setVersion] = useState(release?.version ?? "");
  const [description, setDescription] = useState(release?.description ?? "");

  const save = useMutation({
    mutationFn: () =>
      editing
        ? api.patch<Release>(apiReleasePath(release!.id), {
            name: name.trim(),
            version: version.trim(),
            description,
          } satisfies ReleaseUpdate)
        : api.post<Release>(ApiPath.releases, {
            project_id: projectId,
            name: name.trim(),
            version: version.trim(),
            description,
          } satisfies ReleaseCreate),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.releases(projectId) });
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !version.trim()) return;
    save.mutate();
  };

  return (
    <Modal title={editing ? `Edit ${release!.version}` : "New release"} onClose={onClose}>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Version"
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            placeholder="1.2.0"
            maxLength={100}
            required
          />
          <TextField
            label="Name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Winter release"
            maxLength={200}
            required
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="release-desc" className="text-xs font-medium text-fg-secondary">
            Description (optional)
          </label>
          <textarea
            id="release-desc"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            placeholder="What's in this release"
            className="rounded-md border border-strong bg-surface px-2.5 py-1.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
          />
        </div>
        {save.isError && <p className="text-xs text-red-400">{errorMessage(save.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending || !name.trim() || !version.trim()}>
            {save.isPending ? "Saving…" : editing ? "Save changes" : "Create release"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
