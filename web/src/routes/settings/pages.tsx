import { useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, Copy, Pencil, Plus, ShieldCheck, Trash2, X } from "lucide-react";
import { api, ApiError, errorMessage } from "../../lib/api";
import { ApiPath, RoutePath, apiPageSpacePath, publicKbSpaceUrl } from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { usePermissions } from "../../lib/hooks";
import { pageSpacesQuery } from "../../lib/queries";
import {
  Permission,
  type PageSpace,
  type PageSpaceCreate,
  type PageSpaceUpdate,
} from "../../lib/types";
import { Button } from "../../components/Button";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { PublicBadge } from "../../components/pages/PublicBadge";
import { TableSkeleton } from "../../components/TableSkeleton";
import { TextField } from "../../components/TextField";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { SpaceAccessPanel } from "../../components/settings/SpaceAccessPanel";
import { QueryError } from "../../components/QueryError";
import { ErrorText } from "../../components/ErrorText";

/** Page spaces admin (spec 43, doc.manage): create/rename/delete pages spaces. */
export function PagesSettingsPage() {
  const perms = usePermissions();
  // deliberately-global: creating/renaming/deleting SPACES is what this page
  // does, and `create_space` checks PAGE_MANAGE with no space id (RADD-810) —
  // the global question matches the server here even though the atom is
  // space-scoped.
  const canManage = perms.global(Permission.pageManage);
  const spaces = useQuery(pageSpacesQuery());
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<PageSpace | null>(null);
  const [showingAccess, setShowingAccess] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [confirmDialog, confirm] = useConfirm();

  const remove = useMutation({
    mutationFn: ({ spaceId, force }: { spaceId: string; force: boolean }) =>
      api.delete<void>(apiPageSpacePath(spaceId), {
        query: { force: force ? "true" : undefined },
      }),
    onMutate: () => setDeleteError(null),
    onError: (error, { spaceId }) => {
      // 409 = non-empty: offer the cascading force delete.
      if (error instanceof ApiError && error.status === 409) {
        void confirm({
          title: "Delete non-empty space",
          message: "This space still has pages. Delete the space AND all its pages?",
          confirmLabel: "Delete all",
          danger: true,
        }).then((ok) => {
          if (ok) remove.mutate({ spaceId, force: true });
        });
      } else {
        setDeleteError(errorMessage(error));
      }
    },
    onSettled: () => invalidateEntities(queryClient, Entity.docSpace, Entity.page),
  });

  const list = spaces.data ?? [];

  return (
    <SettingsPage
      title="Page spaces"
      description="Wiki spaces, each holding a page tree. A space is a grant SCOPE (RADD-791): who reads, writes and comments in it is a role granted there. Managing a space needs page.manage in it."
    >
      {spaces.isPending ? (
        <TableSkeleton rows={3} />
      ) : spaces.isError ? (
        <QueryError label="page spaces" error={spaces.error} />
      ) : (
        <>
          {deleteError && <ErrorText className="mb-3" error={deleteError} />}
          {list.length === 0 ? (
            <EmptyState icon={BookOpen} message="No page spaces yet — create the first one below." />
          ) : (
            <ul className="rounded-lg border border-subtle">
              {list.map((space) => (
                <li
                  key={space.id}
                  className="border-b border-subtle/60 px-4 py-2.5 last:border-b-0"
                >
                  <div className="flex items-center gap-2">
                    <Link
                      to={RoutePath.pageSpace}
                      params={{ spaceSlug: space.slug }}
                      className="text-[13px] font-medium text-heading hover:underline"
                    >
                      {space.name}
                    </Link>
                    <span className="font-mono text-[11px] text-fg-faint">{space.slug}</span>
                    {space.public && <PublicBadge />}
                    <span className="flex-1 text-right text-[11px] text-fg-muted">
                      {space.page_count} page{space.page_count === 1 ? "" : "s"}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setShowingAccess(showingAccess === space.id ? null : space.id)
                      }
                      aria-label={`Access for ${space.name}`}
                      aria-expanded={showingAccess === space.id}
                      className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                    >
                      <ShieldCheck size={13} aria-hidden />
                    </button>
                    {canManage && (
                      <>
                        <button
                          type="button"
                          onClick={() => setEditing(editing?.id === space.id ? null : space)}
                          aria-label={`Edit ${space.name}`}
                          className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                        >
                          <Pencil size={13} aria-hidden />
                        </button>
                        <button
                          type="button"
                          onClick={() => remove.mutate({ spaceId: space.id, force: false })}
                          aria-label={`Delete ${space.name}`}
                          className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-red-300 cursor-pointer"
                        >
                          <Trash2 size={13} aria-hidden />
                        </button>
                      </>
                    )}
                  </div>
                  {space.description && (
                    <p className="mt-0.5 text-xs text-fg-muted">{space.description}</p>
                  )}
                  {editing?.id === space.id && (
                    <SpaceForm existing={space} onDone={() => setEditing(null)} />
                  )}
                  {showingAccess === space.id && (
                    <SpaceAccessPanel
                      spaceId={space.id}
                      spaceName={space.name}
                      canManage={canManage}
                    />
                  )}
                </li>
              ))}
            </ul>
          )}
          {canManage && <SpaceForm />}
        </>
      )}
      {confirmDialog}
    </SettingsPage>
  );
}

/** The shareable /kb URL + a copy button (the spec-62 PublicLinkRow idiom). */
function PublicPagesLinkRow({ spaceId }: { spaceId: string }) {
  const [copied, setCopied] = useState(false);
  const url = publicKbSpaceUrl(spaceId);
  const copy = async () => {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="flex items-center gap-2">
      <input
        readOnly
        value={url}
        onFocus={(event) => event.target.select()}
        className="h-7 min-w-0 flex-1 rounded-md border border-strong bg-surface px-2 font-mono text-[12px] text-fg"
      />
      <Button size="sm" variant="secondary" className="shrink-0" onClick={copy}>
        {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

function SpaceForm({
  existing,
  onDone,
}: {
  existing?: PageSpace;
  onDone?: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [isPublic, setIsPublic] = useState(existing?.public ?? false);

  const save = useMutation({
    mutationFn: () =>
      existing
        ? api.patch<PageSpace>(apiPageSpacePath(existing.id), {
            name: name.trim(),
            description,
            public: isPublic,
          } satisfies PageSpaceUpdate)
        : api.post<PageSpace>(ApiPath.pageSpaces, {
            name: name.trim(),
            description,
          } satisfies PageSpaceCreate),
    onSuccess: () => {
      if (!existing) {
        setName("");
        setDescription("");
      }
      onDone?.();
    },
    onSettled: () => invalidateEntities(queryClient, Entity.docSpace),
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) save.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3">
      <TextField
        label={existing ? "Name" : "New space name"}
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Engineering handbook"
        maxLength={200}
      />
      <TextField
        label="Description (optional)"
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        placeholder="What lives in this space"
      />
      {existing && (
        <div className="flex flex-col gap-2 rounded-lg border border-subtle bg-surface/40 p-3">
          <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(event) => setIsPublic(event.target.checked)}
              className="size-4 accent-accent"
            />
            Public — anyone with the link can read this space's pages, no sign-in
          </label>
          <p className="text-xs text-fg-muted">
            Archived pages stay hidden. Use external image URLs in public pages — attachment
            links still need a login.
          </p>
          {isPublic && <PublicPagesLinkRow spaceId={existing.id} />}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={save.isPending || !name.trim()}>
          <Plus size={14} aria-hidden />
          {save.isPending ? "Saving…" : existing ? "Save changes" : "Create space"}
        </Button>
        {existing && (
          <Button size="sm" variant="ghost" onClick={onDone}>
            <X size={12} aria-hidden />
            Cancel
          </Button>
        )}
        {save.isError && <span className="text-xs text-red-400">{errorMessage(save.error)}</span>}
      </div>
    </form>
  );
}
