import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { AccessGrantsEditor, ErrorText, Modal, PageExtensionCtx, api, useConfirm, useIsAuthenticated } from "@radd/plugin-sdk";
import { pagePath, pageUnarchivePath } from "../endpoints";
import { PageRoute, pageLink } from "../links";
import type { Page } from "../types";
import { ChangeUrlDialog } from "./ChangeUrlDialog";
import { PageEditPanel } from "./PageEditPanel";
import { PageHistory } from "./PageHistory";
import { PageInlineComments } from "./PageInlineComments";
import { PageLabels } from "./PageLabels";
import { ArchivedBanner, PageMeta, PageTab, type PageTabValue } from "./PageMeta";
import { PageReading } from "./PageReading";
import { usePageEditing } from "./usePageEditing";
import { usePeople } from "./people";

/**
 * A page (spec 43): inline-editable title, rendered markdown body with an
 * Edit mode, History tab, archive controls, and the linked-issues panel.
 *
 * Edit mode is a ROOM since spec 122: readers sit in it as observers (the
 * header shows who is there), Edit joins as an editor on a shared document,
 * and the elected saver autosaves. The spec-43 single-editor flow (Save with
 * expected_version; reload-or-overwrite on a 409) is the fallback when the
 * room cannot be joined — see `usePageEditing`.
 */
export function PageView({
  page,
  canWrite: canWriteProp,
  canComment,
  canManage,
  spaceSlug,
}: {
  page: Page;
  canWrite: boolean;
  /** `comment.write`, NOT `page.write` (RADD-770). Separate atoms on the server,
   *  and `page.write` is held unconditionally by every active user — so passing
   *  `canWrite` here was a gate that could never close. */
  canComment: boolean;
  canManage: boolean;
  /** For page-relative extensions (RADD-709) — a `radd:toc` with subpages has
   *  to build links, and only the route knows the space's URL segment. */
  spaceSlug?: string;
}) {
  // RADD-1228: an archived page is READ-ONLY until restored — every editor
  // this component offers hangs off `canWrite`, so closing it here closes them
  // all (title, body, URL, labels, links, history restore). Restore and
  // permanent delete stay on `canManage`.
  const archived = page.archived_at !== null;
  const canWrite = canWriteProp && !archived;
  const authenticated = useIsAuthenticated();
  const users = usePeople(authenticated);
  const navigate = useNavigate();
  const edit = usePageEditing(page);
  const [tab, setTab] = useState<PageTabValue>(PageTab.content);
  const [title, setTitle] = useState(page.title);
  const [restricting, setRestricting] = useState(false);
  const [changingUrl, setChangingUrl] = useState(false);
  const [confirmDialog, confirm] = useConfirm();
  // The rendered body element, and a counter that ticks when it re-renders —
  // anchors resolve against rendered text, so they must be re-scanned then.
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyVersion, setBodyVersion] = useState(0);

  // A concurrent editor may rename the page while we view it — track it.
  useEffect(() => setTitle(page.title), [page.title]);

  const archive = useMutation({ mutationFn: () => api.delete<void>(pagePath(page.id)), onSettled: edit.invalidate });
  const unarchive = useMutation({ mutationFn: () => api.post<Page>(pageUnarchivePath(page.id)), onSettled: edit.invalidate });
  const hardDelete = useMutation({
    mutationFn: () => api.delete<void>(pagePath(page.id), { query: { hard: "true" } }),
    // The page is gone; stay on its space rather than on a 404.
    onSuccess: () => void navigate({ to: PageRoute.space, params: { spaceSlug: page.space.slug } }),
    onSettled: edit.invalidate,
  });
  const { save } = edit;

  const saveTitle = () => {
    const trimmed = title.trim();
    if (trimmed && trimmed !== page.title) save.mutate({ title: trimmed, expected_version: page.version });
    else setTitle(page.title);
  };
  const deletePage = () => void confirm({
    title: "Delete page permanently",
    message: archived
      ? "Permanently delete this page and its history?"
      : "Permanently delete this page and its history? This cannot be undone — Archive keeps it restorable.",
    confirmLabel: "Delete",
    danger: true,
  }).then((ok) => { if (ok) hardDelete.mutate(); });

  const extensionContext = useMemo(
    () => ({ pageId: page.id, spaceId: page.space_id, spaceSlug: spaceSlug ?? null }),
    [page.id, page.space_id, spaceSlug],
  );

  return (
    <PageExtensionCtx.Provider value={extensionContext}>
    <div className="@container/page-view px-6 py-5">
      {archived && <ArchivedBanner spaceSlug={spaceSlug} canManage={canManage} onRestore={() => unarchive.mutate()} />}

      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        onBlur={saveTitle}
        onKeyDown={(event) => {
          if (event.key === "Enter") (event.target as HTMLInputElement).blur();
        }}
        aria-label="Page title"
        maxLength={500}
        readOnly={!canWrite}
        className="w-full rounded-md border border-transparent bg-transparent px-1.5 py-1 text-xl font-semibold text-heading hover:border-subtle focus:border-strong focus:outline-2 focus:outline-offset-1 focus:outline-focus read-only:hover:border-transparent"
      />

      <PageMeta page={page} users={users} people={edit.collab.presence.people} tab={tab} onTab={setTab}
        authenticated={authenticated} canWrite={canWrite} canManage={canManage} spaceSlug={spaceSlug}
        onChangeUrl={() => setChangingUrl(true)} onRestrict={() => setRestricting(true)}
        onArchive={() => archive.mutate()} onDelete={deletePage} />

      <PageLabels pageId={page.id} labels={page.labels ?? []} canWrite={canWrite} />

      {(save.isError && !edit.conflict) || archive.isError || hardDelete.isError ? (
        <ErrorText className="mt-2" error={save.isError ? save.error : archive.isError ? archive.error : hardDelete.error} />
      ) : null}

      {tab === PageTab.history ? (
        <PageHistory page={page} canWrite={canWrite} />
      ) : (
        <div className="grid min-w-0 items-start gap-6 @3xl/page-view:grid-cols-[minmax(0,1fr)_18rem]" data-page-content-layout>
          <div className="min-w-0">
            {edit.editing ? (
              <div ref={bodyRef}>
                <PageEditPanel
                  draft={edit.draft}
                  onDraft={edit.onDraft}
                  pendingAiRun={edit.pendingAiRun}
                  // Pasted/inserted images go through the storage-choice seam (spec 102).
                  attachTo={{ entityType: "page", entityId: page.id }}
                  collab={edit.collab}
                  legacy={edit.legacy}
                  editVersion={edit.editVersion}
                  conflict={edit.conflict}
                  saving={save.isPending}
                  onSave={(body) => save.mutate(body)}
                  onReload={edit.reload}
                  onCancel={edit.cancel}
                  finishing={edit.finishing}
                  inlineAnchors={edit.inlineAnchors}
                  onDetachedComments={edit.resolveDetached}
                  onDone={() => void edit.done()}
                />
              </div>
            ) : (
              <PageReading page={page} bodyRef={bodyRef} canWrite={canWrite} canComment={canComment}
                onEdit={edit.open} onRendered={() => setBodyVersion((v) => v + 1)} onChanged={edit.invalidate} />
            )}
          </div>
          <aside aria-label="Page annotations" data-page-comment-sidebar
            className="sticky top-3 z-10 order-first min-w-0 max-h-[32vh] overflow-y-auto rounded-lg border border-subtle bg-base p-3 @3xl/page-view:order-last @3xl/page-view:max-h-[calc(100dvh-9rem)]">
            <PageInlineComments
              pageId={page.id}
              bodyRef={bodyRef}
              bodyVersion={bodyVersion}
              editing={edit.editing}
              canComment={canComment}
            />
          </aside>
        </div>
      )}
      {confirmDialog}
      {changingUrl && spaceSlug && (
        <ChangeUrlDialog
          page={page}
          spaceSlug={spaceSlug}
          onSave={(slug) => save.mutate({ slug }, {
            onSuccess: (updated) => {
              setChangingUrl(false);
              // The old slug is freed the moment the rename lands — move to the canonical
              // address rather than 404ing in place.
              void navigate(pageLink(spaceSlug, updated.path));
            },
          })}
          onClose={() => setChangingUrl(false)}
        />
      )}
      {restricting && (
        <Modal title={`Restrict "${page.title}"`} onClose={() => setRestricting(false)}>
          <AccessGrantsEditor
            resourceType="page"
            resourceId={page.id}
            description={
              <>
                Allow grants limit the selected access to their subjects; deny grants
                exclude their subjects without restricting everyone else. Restrictions
                also apply to <strong>subpages</strong>. Space permissions and every
                ancestor restriction still apply: a page grant cannot reopen access
                denied above it.
              </>
            }
          />
        </Modal>
      )}
    </div>
    </PageExtensionCtx.Provider>
  );
}
