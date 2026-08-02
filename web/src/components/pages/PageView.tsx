import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, History, Pencil, Trash2 } from "lucide-react";
import { api, ApiError, errorMessage } from "../../lib/api";
import { useAttachmentUploader } from "../../lib/useAttachmentUploader";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiPagePath, apiPageUnarchivePath, attachmentUrl } from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import { LazyRichViewer as RichViewer } from "../editor/LazyRichViewer";
import { usersQuery } from "../../lib/queries";
import { AttachmentParentType, type Page, type PageUpdate } from "../../lib/types";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import type { AiRun } from "../editor/ai";
import { AiReadMenu } from "../editor/AiReadMenu";
import { Button } from "../Button";
import { useConfirm } from "../ConfirmDialog";
import { PageLinkedItems } from "./PageLinkedItems";
import { PageHistory } from "./PageHistory";

const Tab = { content: "content", history: "history" } as const;
type TabValue = (typeof Tab)[keyof typeof Tab];

/**
 * A page (spec 43): inline-editable title, rendered markdown body with an
 * Edit mode (optimistic concurrency: Save sends expected_version; a 409 offers
 * reload-or-overwrite instead of clobbering), History tab, archive controls,
 * and the linked-issues panel.
 */
export function PageView({
  page,
  canWrite,
  canManage,
}: {
  page: Page;
  canWrite: boolean;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const { data: users } = useQuery(usersQuery);
  const [tab, setTab] = useState<TabValue>(Tab.content);
  const [title, setTitle] = useState(page.title);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(page.body);
  /** The version the edit session was OPENED at — the optimistic-concurrency
   * anchor. A realtime refetch may bump page.version mid-edit; saving must
   * still 409 against the version the author actually read. */
  const [editVersion, setEditVersion] = useState(page.version);
  const [conflict, setConflict] = useState(false);
  // A read-mode AI transform pending for the edit session about to open —
  // handed to the editor as its initial whole-document run.
  const [pendingAiRun, setPendingAiRun] = useState<AiRun | null>(null);
  const [confirmDialog, confirm] = useConfirm();
  // Pasted/inserted page images go through the storage-choice seam (spec 102).
  const uploadFiles = useAttachmentUploader({
    entityType: AttachmentParentType.page,
    entityId: page.id,
  });

  // A concurrent editor may rename the page while we view it — track it.
  useEffect(() => setTitle(page.title), [page.title]);

  const invalidate = () => void invalidateEntities(queryClient, Entity.page, Entity.docSpace);
  const save = useMutation({
    mutationFn: (body: PageUpdate) => api.patch<Page>(apiPagePath(page.id), body),
    onSuccess: () => {
      setEditing(false);
      setConflict(false);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) setConflict(true);
    },
    onSettled: invalidate,
  });
  const archive = useMutation({
    mutationFn: () => api.delete<void>(apiPagePath(page.id)),
    onSettled: invalidate,
  });
  const unarchive = useMutation({
    mutationFn: () => api.post<Page>(apiPageUnarchivePath(page.id)),
    onSettled: invalidate,
  });
  const hardDelete = useMutation({
    mutationFn: () => api.delete<void>(apiPagePath(page.id), { query: { hard: "true" } }),
    onSettled: invalidate,
  });

  const saveTitle = () => {
    const trimmed = title.trim();
    if (trimmed && trimmed !== page.title) {
      save.mutate({ title: trimmed, expected_version: page.version });
    } else {
      setTitle(page.title);
    }
  };

  const author = users?.find((user) => user.id === page.updated_by);
  const archived = page.archived_at !== null;

  return (
    <div className="px-6 py-5">
      {archived && (
        <p className="mb-3 flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
          <Archive size={13} aria-hidden />
          This page is archived — it's hidden from the tree until restored.
          {canManage && (
            <button
              type="button"
              onClick={() => unarchive.mutate()}
              className="ml-auto flex items-center gap-1 rounded border border-amber-500/40 px-1.5 py-0.5 hover:bg-amber-500/10 cursor-pointer"
            >
              <ArchiveRestore size={12} aria-hidden />
              Restore
            </button>
          )}
        </p>
      )}

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

      <div className="mt-1 flex items-center gap-2 px-1.5 text-xs text-fg-muted">
        <span>
          Updated by {author?.name ?? "someone"}{" "}
          <span title={page.updated_at}>{relativeTime(page.updated_at)}</span>
        </span>
        <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
          v{page.version}
        </span>
        <span className="ml-auto flex items-center gap-1">
          <TabButton
            active={tab === Tab.content}
            onClick={() => setTab(Tab.content)}
            label="Content"
          />
          <TabButton
            active={tab === Tab.history}
            onClick={() => setTab(Tab.history)}
            label="History"
            icon={<History size={11} aria-hidden />}
          />
          {canWrite && !archived && (
            <button
              type="button"
              onClick={() => archive.mutate()}
              title="Archive — hidden from the tree until restored"
              className="ml-1 rounded p-1 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
            >
              <Archive size={13} aria-hidden />
            </button>
          )}
          {canManage && archived && (
            <button
              type="button"
              onClick={() =>
                void confirm({
                  title: "Delete page permanently",
                  message: "Permanently delete this page and its history?",
                  confirmLabel: "Delete",
                  danger: true,
                }).then((ok) => {
                  if (ok) hardDelete.mutate();
                })
              }
              title="Delete permanently"
              className="ml-1 rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
            >
              <Trash2 size={13} aria-hidden />
            </button>
          )}
        </span>
      </div>

      {(save.isError && !conflict) || archive.isError || hardDelete.isError ? (
        <p className="mt-2 text-xs text-red-400">
          {errorMessage(save.isError ? save.error : archive.isError ? archive.error : hardDelete.error)}
        </p>
      ) : null}

      {tab === Tab.history ? (
        <PageHistory page={page} canWrite={canWrite} />
      ) : editing ? (
        <div className="mt-3 flex flex-col gap-2">
          {conflict && (
            <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
              This page changed since you opened it — reload it (discarding your draft) or
              overwrite.
              <span className="ml-auto flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setConflict(false);
                    setEditing(false);
                    invalidate();
                  }}
                  className="rounded border border-amber-500/40 px-1.5 py-0.5 hover:bg-amber-500/10 cursor-pointer"
                >
                  Reload
                </button>
                <button
                  type="button"
                  onClick={() => save.mutate({ body: draft })}
                  className="rounded border border-amber-500/40 px-1.5 py-0.5 hover:bg-amber-500/10 cursor-pointer"
                >
                  Overwrite
                </button>
              </span>
            </div>
          )}
          <RichEditor
            value={draft}
            onChange={setDraft}
            onUploadImage={async (file) => {
              const [attachment] = await uploadFiles([file]);
              return attachmentUrl(attachment.id);
            }}
            autoFocus
            placeholder="Write the page… use the toolbar for headings, tables, code — or type markdown."
            initialAiRun={pendingAiRun ?? undefined}
            className="[&_.ProseMirror]:min-h-[24rem]"
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => save.mutate({ body: draft, expected_version: editVersion })}
              disabled={save.isPending}
            >
              {save.isPending ? "Saving…" : "Save"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(false);
                setConflict(false);
                setPendingAiRun(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          {page.body ? (
            <div className="group/body relative mt-3 rounded-md border border-transparent px-1.5 py-1 hover:border-subtle">
              <RichViewer text={page.body} />
              <span className="absolute right-1 top-1 hidden items-center gap-1 group-hover/body:flex">
                {/* Read-mode AI (spec 103 follow-up): find-similar/summarize for
                    every reader; transforms only for writers. */}
                <AiReadMenu
                  text={page.body}
                  similar={{ seedKey: page.id }}
                  onTransform={
                    canWrite
                      ? (run) => {
                          setDraft(page.body);
                          setEditVersion(page.version);
                          setPendingAiRun(run);
                          setEditing(true);
                        }
                      : undefined
                  }
                  label="AI actions for this page"
                />
                {canWrite && (
                  <button
                    type="button"
                    onClick={() => {
                      setDraft(page.body);
                      setEditVersion(page.version);
                      setPendingAiRun(null);
                      setEditing(true);
                    }}
                    aria-label="Edit page"
                    title="Edit page"
                    className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                  >
                    <Pencil size={12} aria-hidden />
                  </button>
                )}
              </span>
            </div>
          ) : canWrite ? (
            <button
              type="button"
              onClick={() => {
                setDraft(page.body);
                setEditVersion(page.version);
                setEditing(true);
              }}
              className="mt-3 rounded-md border border-transparent px-1.5 py-1 text-left text-[13px] text-fg-faint hover:border-subtle hover:text-fg-secondary cursor-pointer"
            >
              Write something…
            </button>
          ) : (
            <p className="mt-3 px-1.5 text-[13px] text-fg-faint">This page is empty.</p>
          )}

          <section className="mt-8 border-t border-subtle pt-4">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-fg-muted">
              Linked issues
            </h3>
            <PageLinkedItems pageId={page.id} canWrite={canWrite} />
          </section>
        </>
      )}
      {confirmDialog}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  label,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  icon?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium cursor-pointer " +
        (active ? "bg-elevated text-heading" : "text-fg-muted hover:text-fg")
      }
    >
      {icon}
      {label}
    </button>
  );
}
