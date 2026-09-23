import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, Pencil, Plus, Rocket, Ship, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { ApiPath, apiReleasePath, apiReleaseSweepPath } from "../lib/constants";
import { formatDate } from "../lib/dates";
import { usePermissions, useProjectByKey } from "../lib/hooks";
import { useListFilter } from "../lib/list-filter";
import { RELEASE_STATUS_META } from "../lib/meta";
import { projectByIdQuery, queryKeys, releasesQuery, statesQuery, transitionsQuery } from "../lib/queries";
import { RoutePath } from "../lib/constants";
import { Entity, entityMeta, invalidateEntities } from "../lib/cache";
import { pushToast, ToastKind } from "../lib/toast";
import {
  Permission,
  ReleaseStatus,
  type Item,
  type Release,
  type ReleaseCreate,
  type ReleaseSweepResult,
  type ReleaseUpdate,
} from "../lib/types";
import { Button } from "../components/Button";
import { useConfirm } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { ListSearchInput } from "../components/ListSearchInput";
import { Modal } from "../components/Modal";
import { TableSkeleton } from "../components/TableSkeleton";
import { TextField } from "../components/TextField";
import { Link, useParams } from "@tanstack/react-router";
import { QueryError } from "../components/QueryError";
import { IconButton } from "../components/IconButton";
import { ErrorText } from "../components/ErrorText";

/**
 * A project's releases (RADD-1290): a PROJECT page, readable by anyone who can
 * read the project — what shipped in 1.2 is content, not configuration, and it
 * used to live only under Project settings, out of reach without release.update.
 * Create, edit, mark released, sweep and delete appear for those who may.
 */
export function ProjectReleasesPage() {
  const { projectKey = "" } = useParams({ strict: false });
  const byKey = useProjectByKey(projectKey);
  const projectId = byKey.project?.id;
  const perms = usePermissions();
  const projectQuery = useQuery({ ...projectByIdQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const [modal, setModal] = useState<{ release: Release | null } | null>(null);

  const project = projectQuery.data;
  // Releases are per-project: gate on THAT project's manage permission.
  const canManage = perms.project(project, Permission.releaseUpdate);
  const releases = useQuery({ ...releasesQuery(projectId ?? ""), enabled: Boolean(projectId) });
  const all = releases.data ?? [];
  const search = useListFilter(all, (release) => [release.version, release.name]);
  const list = search.filtered;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-subtle px-5 py-3">
        <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-fg">{projectKey}</span>
        <h1 className="text-sm font-semibold text-heading">{project?.name ?? projectKey} · Releases</h1>
        {canManage && project && (
          <Button size="sm" className="ml-auto" onClick={() => setModal({ release: null })}>
            <Plus size={14} aria-hidden />
            New release
          </Button>
        )}
      </header>
      <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-5">
      <p className="mb-4 text-xs text-fg-muted">
        Versions of this project. Mark one released when it ships; open it to see what shipped.
      </p>
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

      {/* RADD-1285: what a published release moves is a workflow fact — the
          on-release transitions — shown here and edited in Workflow. */}
      {project && <ShippingSummary projectId={project.id} projectKey={project.key} />}

      {modal && project && (
        <ReleaseModal
          projectId={project.id}
          release={modal.release}
          onClose={() => setModal(null)}
        />
      )}
      </div>
      </div>
    </div>
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
  const [open, setOpen] = useState(false);
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
    <li className="border-b border-subtle/60 last:border-b-0" data-release={release.version}>
      <div className="flex items-center gap-3 px-4 py-2.5">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        aria-label={`${open ? "Hide" : "Show"} the issues in ${release.version}`}
        className="shrink-0 rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer focus-visible:outline-2 focus-visible:outline-focus">
        <ChevronRight size={13} aria-hidden className={open ? "rotate-90 transition-transform" : "transition-transform"} />
      </button>
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
              title="Ship every issue waiting for release into this version"
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
                message: "Issues pointing at this release keep their history; the version itself goes.",
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
      </div>
      {open && <ReleaseIssues projectId={projectId} release={release} />}
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


/** Which moves a published release performs in this project (RADD-1285). */
function ShippingSummary({ projectId, projectKey }: { projectId: string; projectKey: string }) {
  const transitions = useQuery(transitionsQuery(projectId));
  const states = useQuery(statesQuery(projectId));
  const name = new Map((states.data ?? []).map((state) => [state.id, state.name]));
  const shipping = (transitions.data ?? []).filter((row) => row.on_release && row.from_state_id);
  return (
    <section aria-label="How releases ship" className="mt-8" data-release-shipping>
      <h3 className="text-[13px] font-semibold text-heading">How releases ship</h3>
      {shipping.length === 0 ? (
        <p className="mt-0.5 text-xs text-fg-muted">
          Publishing a release records it but moves nothing. To ship finished work automatically,
          mark a transition <em>Moves automatically when a release is published</em> in{" "}
          <Link to={RoutePath.projectSettingsWorkflow} params={{ projectKey }} className="text-accent-text hover:underline">
            Workflow
          </Link>.
        </p>
      ) : (
        <>
          <p className="mt-0.5 text-xs text-fg-muted">
            Publishing a release — here, over the API, or from GitHub, GitLab or Forgejo — moves:
          </p>
          <ul className="mt-2 flex flex-col gap-1 text-[13px] text-fg">
            {shipping.map((row) => (
              <li key={row.id} data-release-move={row.id}>
                {name.get(row.from_state_id ?? "") ?? "?"} → {name.get(row.to_state_id) ?? "?"}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-fg-muted">
            Change this in{" "}
            <Link to={RoutePath.projectSettingsWorkflow} params={{ projectKey }} className="text-accent-text hover:underline">
              Workflow
            </Link>.
          </p>
        </>
      )}
    </section>
  );
}


/** The issues recorded against one release (RADD-1290): what shipped in it,
 *  or what is targeted at it while it is still planned. */
function ReleaseIssues({ projectId, release }: { projectId: string; release: Release }) {
  const issues = useQuery({
    queryKey: ["release-issues", release.id],
    meta: entityMeta(Entity.item),
    queryFn: ({ signal }) =>
      api.get<Item[]>(ApiPath.items, {
        signal,
        query: { project_id: projectId, q: `release = "${release.version.replace(/"/g, '\\"')}"`, limit: "200" },
      }),
  });
  if (issues.isPending) return <p className="px-11 pb-3 text-xs text-fg-muted">Loading issues…</p>;
  if (issues.isError) return <div className="px-11 pb-3"><QueryError label="issues" error={issues.error} /></div>;
  if (issues.data.length === 0) {
    return (
      <p className="px-11 pb-3 text-xs text-fg-muted">
        {release.status === ReleaseStatus.released ? "No issues recorded against this release." : "No issues target this release yet."}
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-1 px-11 pb-3" data-release-issues={release.version}>
      {issues.data.map((item) => (
        <li key={item.id} className="flex items-center gap-2 text-[13px]">
          <Link to={RoutePath.issue} params={{ itemKey: item.key }} className="font-mono text-xs text-fg-muted hover:text-accent-text">
            {item.key}
          </Link>
          <span className="truncate text-fg">{item.title}</span>
          <span className="ml-auto shrink-0 text-xs text-fg-muted">{item.state?.name}</span>
        </li>
      ))}
    </ul>
  );
}
