import { useIsAuthenticated } from "../../lib/hooks";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  Link2,
  Archive,
  ArchiveRestore,
  Download,
  History,
  Lock,
  Pencil,
  Printer,
  Trash2,
} from "lucide-react";
import { api, ApiError } from "../../lib/api";
import { useAttachmentUploader } from "../../lib/useAttachmentUploader";
import { Entity, invalidateEntities } from "../../lib/cache";
import {
  RoutePath,
  apiPageExportPath,
  apiPagePath,
  apiPageUnarchivePath,
  attachmentUrl,
} from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import { AccessGrantsEditor } from "../settings/AccessGrantsEditor";
import { Modal } from "../Modal";
import { PageBody } from "./PageBody";
import { usersQuery } from "../../lib/queries";
import { AttachmentParentType, type Page, type PageUpdate } from "../../lib/types";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import type { AiRun } from "../editor/ai";
import { AiReadMenu } from "../editor/AiReadMenu";
import { Button } from "../Button";
import { useConfirm } from "../ConfirmDialog";
import { DropdownMenu } from "../DropdownMenu";
import { PageExtensionCtx } from "../../lib/page-extensions";
import { PageBacklinksPanel } from "./PageBacklinksPanel";
import { PageComments } from "./PageComments";
import { PageWatchButton } from "./PageWatchButton";
import { PageInlineComments } from "./PageInlineComments";
import { PageLabels } from "./PageLabels";
import { PageLinkedItems } from "./PageLinkedItems";
import { PageHistory } from "./PageHistory";
import { IconButton } from "../IconButton";
import { ErrorText } from "../ErrorText";
import { Callout } from "../Callout";

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
  const queryClient = useQueryClient();
  const { data: users } = useQuery({ ...usersQuery, enabled: useIsAuthenticated() });
  const [tab, setTab] = useState<TabValue>(Tab.content);
  const [title, setTitle] = useState(page.title);
  const [editing, setEditing] = useState(false);
  const [restricting, setRestricting] = useState(false);
  const [changingUrl, setChangingUrl] = useState(false);
  const navigate = useNavigate();
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
  // The rendered body element, and a counter that ticks when it re-renders —
  // anchors resolve against rendered text, so they must be re-scanned then.
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyVersion, setBodyVersion] = useState(0);
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

  /** RADD-733: a new tab, so the reader keeps their place — the print view
   *  replaces the whole document and the browser's print dialog blocks it. */
  const openPrint = (subpages: boolean) => {
    if (!spaceSlug) return;
    const query = subpages ? "?subpages=1" : "";
    window.open(`/pages/${spaceSlug}/${page.slug}/print${query}`, "_blank", "noopener");
  };

  const extensionContext = useMemo(
    () => ({ pageId: page.id, spaceId: page.space_id, spaceSlug: spaceSlug ?? null }),
    [page.id, page.space_id, spaceSlug],
  );

  return (
    <PageExtensionCtx.Provider value={extensionContext}>
    <div className="px-6 py-5">
      {archived && (
        <Callout kind="warning" icon={Archive} className="mb-3">
          <div className="flex items-center gap-2">
            This page is archived — it's hidden from the tree until restored.
            {canManage && (
              <button
                type="button"
                onClick={() => unarchive.mutate()}
                className="ml-auto flex items-center gap-1 rounded border border-callout-warning-border/60 px-1.5 py-0.5 hover:bg-callout-warning-border/10 cursor-pointer"
              >
                <ArchiveRestore size={12} aria-hidden />
                Restore
              </button>
            )}
          </div>
        </Callout>
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

      <div className="mt-1 flex flex-wrap items-center gap-2 px-1.5 text-xs text-fg-muted">
        <span className="min-w-0 break-words">
          Updated by {author?.name ?? "someone"}{" "}
          <span title={page.updated_at}>{relativeTime(page.updated_at)}</span>
        </span>
        <span className="shrink-0 rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
          v{page.version}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-1">
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
          <PageWatchButton pageId={page.id} />
          {canWrite && (
            <IconButton
              onClick={() => setChangingUrl(true)}
              title="Change this page's URL"
              aria-label="Change URL"
              className="flex"
            >
              <Link2 size={13} aria-hidden />
            </IconButton>
          )}
          {/* RADD-738: the export entry point, with the subpages choice offered
              WHERE the action is taken rather than buried in settings. */}
          <DropdownMenu
            label="Export this page"
            align="end"
            className="ml-1"
            widthClass="w-56"
            trigger={({ ref, toggle }) => (
              <IconButton
                ref={ref}
                onClick={toggle}
                title="Export as PDF"
                aria-label="Export this page"
                className="flex"
              >
                <Printer size={13} aria-hidden />
              </IconButton>
            )}
            items={[
              {
                kind: "action" as const,
                label: "Export as PDF",
                icon: Printer,
                onSelect: () => openPrint(false),
              },
              {
                kind: "action" as const,
                label: "Export as PDF, with subpages",
                icon: Printer,
                onSelect: () => openPrint(true),
              },
              { kind: "separator" as const },
              {
                kind: "action" as const,
                label: "Download as markdown (.zip)",
                icon: Download,
                // RADD-721: a plain navigation, so the browser's own download
                // handling applies — Content-Disposition names the file.
                onSelect: () => {
                  window.location.href = `/api/v1${apiPageExportPath(page.id)}`;
                },
              },
            ]}
          />
          {/* RADD-792/793: restrict this ONE page, over the generic spec-92
              editor. Offered where the page is, not in settings — the decision
              is about this page and is made while reading it. */}
          {canManage && (
            <IconButton
              onClick={() => setRestricting(true)}
              title="Restrict who can see this page"
              aria-label="Restrict page"
              className="ml-1"
            >
              <Lock size={13} aria-hidden />
            </IconButton>
          )}
          {canWrite && !archived && (
            <IconButton
              onClick={() => archive.mutate()}
              title="Archive — hidden from the tree until restored"
              aria-label="Archive page"
              className="ml-1"
            >
              <Archive size={13} aria-hidden />
            </IconButton>
          )}
          {canManage && archived && (
            <IconButton
              danger
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
              aria-label="Delete page permanently"
              className="ml-1"
            >
              <Trash2 size={13} aria-hidden />
            </IconButton>
          )}
        </span>
      </div>

      <PageLabels pageId={page.id} labels={page.labels ?? []} canWrite={canWrite} />

      {(save.isError && !conflict) || archive.isError || hardDelete.isError ? (
        <ErrorText className="mt-2" error={save.isError ? save.error : archive.isError ? archive.error : hardDelete.error} />
      ) : null}

      {tab === Tab.history ? (
        <PageHistory page={page} canWrite={canWrite} />
      ) : editing ? (
        <div aria-label="Edit page content" className="mt-3 flex flex-col gap-2">
          {conflict && (
            <Callout kind="warning">
              <div className="flex items-center gap-2">
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
                    className="rounded border border-callout-warning-border/60 px-1.5 py-0.5 hover:bg-callout-warning-border/10 cursor-pointer"
                  >
                    Reload
                  </button>
                  <button
                    type="button"
                    onClick={() => save.mutate({ body: draft })}
                    className="rounded border border-callout-warning-border/60 px-1.5 py-0.5 hover:bg-callout-warning-border/10 cursor-pointer"
                  >
                    Overwrite
                  </button>
                </span>
              </div>
            </Callout>
          )}
          <RichEditor
            value={draft}
            onChange={setDraft}
            extensions
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
            <div
              ref={bodyRef}
              className="mt-3 rounded-md px-1.5 py-1"
            >
              <div className="mb-2 flex flex-wrap items-center justify-end gap-1">
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
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setDraft(page.body);
                      setEditVersion(page.version);
                      setPendingAiRun(null);
                      setEditing(true);
                    }}
                    aria-label="Edit page"
                    title="Edit page"
                  >
                    <Pencil size={12} aria-hidden />
                    Edit page
                  </Button>
                )}
              </div>
              <PageBody text={page.body} onReady={() => setBodyVersion((v) => v + 1)} />
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

          {/* RADD-943: the panel owns its heading, because whether it is open
              is a property of what it contains. */}
          <PageLinkedItems pageId={page.id} canWrite={canWrite} />

          {/* RADD-944 deleted the automatic subpage index that used to sit
              here. Children are the page tree's job, and the author's, via
              `radd:children`/`radd:toc` — RADD-714's own suppression rule
              (stand aside when an extension is present) conceded that the
              placed version was the better one. Backlinks stay automatic
              below: "what points at me" cannot be expressed inline any other
              way, which is why `radd:backlinks` is the INLINE alternative
              rather than the only way to get them. */}

          {/* RADD-726: anchored threads beside the passage they are about. */}
          <PageInlineComments
            pageId={page.id}
            bodyRef={bodyRef}
            bodyVersion={bodyVersion}
            canComment={canComment}
          />

          <PageBacklinksPanel pageId={page.id} />

          {/* RADD-717: a page is where a decision gets written down; the
              argument about it needs somewhere to live besides chat. */}
          <PageComments pageId={page.id} canComment={canComment} />
        </>
      )}
      {confirmDialog}
      {changingUrl && spaceSlug && (
        <ChangeUrlDialog
          page={page}
          spaceSlug={spaceSlug}
          onSave={(slug) => {
            save.mutate(
              { slug },
              {
                onSuccess: (updated) => {
                  setChangingUrl(false);
                  // The old slug is freed the moment the rename lands — move
                  // to the canonical address rather than 404ing in place.
                  navigate({
                    to: RoutePath.page,
                    params: { spaceSlug, pageSlug: updated.slug },
                  });
                },
              },
            );
          }}
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


/** RADD-860: the deliberate URL change RADD-702 reserved — a small dialog
 * over the existing PATCH slug machinery (server-side collision suffixing;
 * old UUID links stay alive). Pre-fills from the title, since "make the URL
 * match the name" is the whole errand. */
function ChangeUrlDialog({
  page,
  spaceSlug,
  onSave,
  onClose,
}: {
  page: Page;
  spaceSlug: string;
  onSave: (slug: string) => void;
  onClose: () => void;
}) {
  const suggested = page.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const [slug, setSlug] = useState(page.slug.startsWith("untitled") ? suggested : page.slug);
  return (
    <Modal title="Change URL" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-fg-secondary">
          The page moves to the new address immediately; links that used the page id keep
          working, links that used the old slug do not. If another page holds the URL, a
          numbered suffix is added.
        </p>
        <div className="flex items-center gap-1 text-[13px]">
          <span className="text-fg-muted">/pages/{spaceSlug}/</span>
          <input
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            aria-label="New URL segment"
            autoFocus
            className="h-8 flex-1 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-focus"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => slug.trim() && onSave(slug.trim())} disabled={!slug.trim()}>
            Change URL
          </Button>
        </div>
      </div>
    </Modal>
  );
}
