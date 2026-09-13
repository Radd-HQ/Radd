import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Pencil, Plus, Rocket, Ship, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { ApiPath, apiReleasePath, apiReleaseSweepPath } from "../../lib/constants";
import { formatDate } from "../../lib/dates";
import { usePermissions } from "../../lib/hooks";
import { useListFilter } from "../../lib/list-filter";
import { RELEASE_STATUS_META } from "../../lib/meta";
import { projectByIdQuery, queryKeys, releasesQuery } from "../../lib/queries";
import { Entity, invalidateEntities } from "../../lib/cache";
import { pushToast, ToastKind } from "../../lib/toast";
import {
  Permission,
  ReleaseStatus,
  SettingScope,
  type Release,
  type ReleaseCreate,
  type ReleaseSweepResult,
  type ReleaseUpdate,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { ListSearchInput } from "../../components/ListSearchInput";
import { Modal } from "../../components/Modal";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { ScopedSettingsEditor } from "../../components/settings/ScopedSettingsEditor";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { QueryError } from "../../components/QueryError";
import { IconButton } from "../../components/IconButton";
import { ErrorText } from "../../components/ErrorText";

/**
 * Per-project releases (spec 50). The project is supplied by the URL context
 * (`projectId`) rather than an in-page picker; gating is on THAT project.
 */
export function ReleasesSettingsPage({ projectId }: { projectId?: string }) {
  const perms = usePermissions();
  const projectQuery = useQuery(projectByIdQuery(projectId ?? ""));
  const [modal, setModal] = useState<{ release: Release | null } | null>(null);

  const project = projectQuery.data;
  // Releases are per-project: gate on THAT project's manage permission.
  const canManage = perms.project(project, Permission.releaseUpdate);
  const releases = useQuery({ ...releasesQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const all = releases.data ?? [];
  const search = useListFilter(all, (release) => [release.version, release.name]);
  const list = search.filtered;

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
      {(projectId && projectQuery.isPending) || (projectId && releases.isPending) ? (
        <TableSkeleton rows={4} />
      ) : projectQuery.isError ? (
        <QueryError label="project" error={projectQuery.error} />
      ) : !project ? (
        <EmptyState icon={Rocket} message="Project not found." />
      ) : releases.isError ? (
        <QueryError label="releases" error={releases.error} />
      ) : all.length === 0 ? (
        <EmptyState
          icon={Rocket}
          message={canManage ? "No releases yet — create one to plan a version." : "No releases yet."}
        />
      ) : (
        <>
          {all.length > 8 && (
            <ListSearchInput
              className="mb-3"
              value={search.filter}
              onChange={search.setFilter}
              placeholder="Filter releases by version or name…"
              total={all.length}
              matched={list.length}
              noun="releases"
            />
          )}
          {list.length === 0 ? (
            <EmptyState icon={Rocket} message={`No releases match “${search.filter.trim()}”.`} />
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
        </>
      )}

      {/* RADD-930: the two states that DRIVE the list above (spec 112), on the
          page that uses them. They used to sit on project → General, where
          "Shipped state" read as trivia with nothing nearby saying what moves
          work there. */}
      {project && (
        <section aria-label="Release pipeline" className="mt-8">
          <h3 className="text-[13px] font-semibold text-heading">Release pipeline</h3>
          <p className="mb-3 mt-0.5 text-xs text-fg-muted">
            Marking a version released — here, over the API, or by a published GitHub or
            Forgejo release — <strong>sweeps</strong> every item sitting in the waiting state
            into the shipped state and records the release on each one. Work that reaches the
            waiting state afterwards ships with the next <em>Sweep</em>. Both are state names,
            resolved within this project — renaming a state is a settings edit here, not a
            broken pipeline. Leave either empty to turn that half off.
          </p>
          <ScopedSettingsEditor
            scope={SettingScope.project}
            scopeId={project.id}
            section="releases"
          />
        </section>
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
  // useConfirm like every sibling page — this row carried the app's one
  // hand-rolled inline Delete/Cancel confirm (RADD-901).
  const [confirmDialog, confirm] = useConfirm();
  const status = RELEASE_STATUS_META[release.status];
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.releases(projectId) });

  // RADD-1007: becoming released sweeps server-side, so every cached item
  // read is stale too — invalidate by entity tag, not by query family.
  const invalidateItems = () => invalidateEntities(queryClient, Entity.item);
  const markReleased = useMutation({
    mutationFn: () =>
      api.patch<Release>(apiReleasePath(release.id), {
        status: ReleaseStatus.released,
      } satisfies ReleaseUpdate),
    onSuccess: async () => {
      await Promise.all([invalidate(), invalidateItems()]);
    },
  });
  const sweep = useMutation({
    mutationFn: () => api.post<ReleaseSweepResult>(apiReleaseSweepPath(release.id)),
    onSuccess: async (result) => {
      pushToast(
        result.items_shipped === 0
          ? `Nothing was waiting for ${release.version}.`
          : `${release.version}: ${result.items_shipped} item${result.items_shipped === 1 ? "" : "s"} shipped.`,
        ToastKind.success,
      );
      await invalidateItems();
    },
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
          ? `Released ${formatDate(release.released_at)}`
          : "—"}
      </span>
      {canManage && (
        <>
          {release.status === ReleaseStatus.planned ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => markReleased.mutate()}
              disabled={markReleased.isPending}
            >
              <CheckCircle2 size={12} aria-hidden />
              {markReleased.isPending ? "Releasing…" : "Mark released"}
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => sweep.mutate()}
              disabled={sweep.isPending}
              title="Ship every item waiting for release into this version"
            >
              <Ship size={12} aria-hidden />
              {sweep.isPending ? "Sweeping…" : "Sweep"}
            </Button>
          )}
          <IconButton
            onClick={onEdit}
            aria-label={`Edit ${release.version}`}
          >
            <Pencil size={13} />
          </IconButton>
          <IconButton
            danger
            onClick={() =>
              void confirm({
                title: `Delete ${release.version}?`,
                message: "Items pointing at this release keep their history; the version itself goes.",
                confirmLabel: "Delete",
                danger: true,
              }).then((ok) => {
                if (ok) remove.mutate();
              })
            }
            disabled={remove.isPending}
            aria-label={`Delete ${release.version}`}
          >
            <Trash2 size={13} />
          </IconButton>
        </>
      )}
      {confirmDialog}
      {(markReleased.isError || sweep.isError || remove.isError) && (
        <ErrorText error={markReleased.error ?? sweep.error ?? remove.error} />
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
        {save.isError && <ErrorText error={save.error} />}
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
