import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Pencil, ShieldCheck, Trash2 } from "lucide-react";
import { api, ApiError, errorMessage } from "../../lib/api";
import { ApiPath, RoutePath, apiPageSpacePath } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { usePageSpaceDirectory } from "../../lib/usePageSpaceDirectory";
import { Permission, type PageSpace } from "../../lib/types";
import { Button } from "../../components/Button";
import { IconButton } from "../../components/IconButton";
import { DirectoryPager } from "../../components/DirectoryPager";
import { ListSearchInput } from "../../components/ListSearchInput";
import { Modal } from "../../components/Modal";
import { pushToast } from "../../lib/toast";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { PublicBadge } from "../../components/pages/PublicBadge";
import { TableSkeleton } from "../../components/TableSkeleton";
import { PageTemplatesSection } from "../../components/settings/PageTemplatesSection";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { SpaceAccessPanel } from "../../components/settings/SpaceAccessPanel";
import { SpaceForm } from "../../components/settings/SpaceForm";
import { QueryError } from "../../components/QueryError";
import { ErrorText } from "../../components/ErrorText";

/** Space mutations follow this space's authority; instance operations stay global. */
export function PagesSettingsPage() {
  const perms = usePermissions();
  // deliberately-global: creation, template CRUD and full link reindex check PAGE_MANAGE without a space ID.
  const canManageInstance = perms.global(Permission.pageManage);
  const canGrant = perms.global(Permission.roleUpdate);
  const spaces = usePageSpaceDirectory();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<PageSpace | null>(null);
  const [showingAccess, setShowingAccess] = useState<PageSpace | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [confirmDialog, confirm] = useConfirm();

  const remove = useMutation({
    mutationFn: ({ spaceId, force }: { spaceId: string; force: boolean }) =>
      api.delete<void>(apiPageSpacePath(spaceId), { query: { force: force ? "true" : undefined } }),
    onMutate: () => setDeleteError(null),
    onError: (error, { spaceId }) => {
      if (error instanceof ApiError && error.status === 409) {
        void confirm({ title: "Delete non-empty space", message: "This space still has pages. Delete the space AND all its pages?", confirmLabel: "Delete all", danger: true })
          .then(ok => { if (ok) remove.mutate({ spaceId, force: true }); });
      } else setDeleteError(errorMessage(error));
    },
    onSettled: () => invalidateEntities(queryClient, Entity.docSpace, Entity.page),
  });
  const reindex = useMutation({
    mutationFn: () => api.post<{ backlinks: number; item_links: number }>(ApiPath.pagesReindex),
    onSuccess: counts => pushToast(`Link index rebuilt: ${counts.backlinks} backlinks, ${counts.item_links} issue links`),
    onError: error => pushToast(errorMessage(error)),
  });

  return <SettingsPage title="Page spaces" description="Organize wiki pages into spaces. Roles in each space control who can read, edit and manage it.">
    {canManageInstance && <div className="mb-3 flex justify-end"><Button variant="ghost" onClick={() => reindex.mutate()} disabled={reindex.isPending}
      title="Rebuild backlinks and issue links from every live page.">{reindex.isPending ? "Rebuilding…" : "Rebuild link index"}</Button></div>}
    <ListSearchInput value={spaces.filter} onChange={spaces.setFilter} placeholder="Find spaces by name or slug…" total={spaces.filter.trim() ? undefined : spaces.total} matched={spaces.total} noun="spaces" />
    {deleteError && <ErrorText className="my-3" error={deleteError} />}
    <div aria-busy={spaces.busy} className="mt-3">
      {spaces.isPending ? <TableSkeleton rows={3} /> : spaces.isError ? <div className="space-y-2">
        <QueryError label="page spaces" error={spaces.error} /><Button variant="secondary" onClick={() => void spaces.refetch()}>Retry spaces</Button>
      </div> : spaces.rows.length === 0 ? <EmptyState icon={BookOpen} message={spaces.filter.trim() ? `No spaces match “${spaces.filter.trim()}”.` : "No page spaces yet."} />
        : <ul aria-label="Manage page spaces" className="rounded-lg border border-subtle">{spaces.rows.map(space => <li key={space.id} className="border-b border-subtle/60 px-4 py-2.5 last:border-b-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Link to={RoutePath.pageSpace} params={{ spaceSlug: space.slug }} className="min-w-0 break-words text-[13px] font-medium text-heading hover:underline">{space.name}</Link>
            <span className="min-w-0 break-all font-mono text-[11px] text-fg-faint">{space.slug}</span>
            {space.public && <PublicBadge />}
            <span className="ml-auto text-[11px] text-fg-muted">{space.page_count} page{space.page_count === 1 ? "" : "s"}</span>
            <IconButton aria-label={`Access for ${space.name}`} onClick={() => setShowingAccess(space)}><ShieldCheck size={13} aria-hidden /></IconButton>
            {perms.space(space, Permission.pageManage) && <>
              <IconButton aria-label={`Edit ${space.name}`} onClick={() => setEditing(space)}><Pencil size={13} aria-hidden /></IconButton>
              <IconButton danger disabled={remove.isPending} aria-label={`Delete ${space.name}`} onClick={() => {
                void confirm({ title: "Delete space", message: `Delete “${space.name}”?`, confirmLabel: "Delete", danger: true }).then(ok => { if (ok) remove.mutate({ spaceId: space.id, force: false }); });
              }}><Trash2 size={13} aria-hidden /></IconButton>
            </>}
          </div>
          {space.description && <p className="mt-0.5 break-words text-xs text-fg-muted">{space.description}</p>}
        </li>)}</ul>}
    </div>
    <DirectoryPager {...spaces} onPage={spaces.setPage} label="managed spaces" />
    {canManageInstance && <><SpaceForm /><PageTemplatesSection /></>}
    {editing && <Modal title={`Edit ${editing.name}`} onClose={() => setEditing(null)}><SpaceForm existing={editing} onDone={() => setEditing(null)} /></Modal>}
    {showingAccess && <Modal title={`Access for ${showingAccess.name}`} onClose={() => setShowingAccess(null)}>
      <SpaceAccessPanel spaceId={showingAccess.id} spaceName={showingAccess.name} canManage={canGrant} />
    </Modal>}
    {confirmDialog}
  </SettingsPage>;
}
