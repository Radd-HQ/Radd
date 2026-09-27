import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus } from "lucide-react";
import {
  Button, CommentHistory, CommentSection, RichEditor, api, errorMessage, invalidateEntities, locateAnchor,
  rangeForOffsets, renderedText, revealTextOffset, scrollRangeIntoView, useCommentFeed, useConfirm,
  useLandOnComment, useLinkedComment, useThreadExpansion, type CommentRow, type TextAnchor,
} from "@radd/plugin-sdk";
import { commentPath, pageCommentsPath } from "../endpoints";
import { Tag } from "../queries";
import { PageCommentThread as Thread } from "./PageCommentThread";
import { PageCommentPopover } from "./PageCommentPopover";
import { useCommentPointer } from "./useCommentPointer";
import { useInlineAnchors } from "./useInlineAnchors";

/** Inline, anchored, resolvable comments (RADD-726): the rail, the floating thread, commenting on a
 *  selection. Anchors resolve against RENDERED text — the quote is the words someone selected. */
export function PageInlineComments({
  pageId,
  bodyRef,
  bodyVersion,
  editing = false,
  canComment,
}: {
  pageId: string;
  /** The element the page body renders into — the anchors' coordinate space. */
  bodyRef: React.RefObject<HTMLElement | null>;
  /** Bump to re-scan after the body re-renders (a save, a lazy segment). */
  bodyVersion: number;
  editing?: boolean;
  canComment: boolean;
}) {
  const queryClient = useQueryClient();
  // RADD-1297: a link to an inline comment widens the rail's feed through it.
  const linked = useLinkedComment(pageId);
  const linkedInline = linked?.anchored ? linked : null;
  const history = useCommentFeed({
    parentType: "page", parentId: pageId, section: CommentSection.inline, through: linkedInline?.root_id,
  });
  const [draftAnchor, setDraftAnchor] = useState<TextAnchor | null>(null);
  const [draftBody, setDraftBody] = useState("");
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const navigation = useRef(0);
  const [showResolved, setShowResolved] = useState(false);
  const railRef = useRef<HTMLElement>(null);
  const invalidate = () => void invalidateEntities(queryClient, Tag.comment);
  const post = useMutation({
    mutationFn: (payload: { body: string; anchor: TextAnchor }) =>
      api.post(pageCommentsPath(pageId), payload),
    onSuccess: () => {
      setDraftAnchor(null);
      setDraftBody("");
    },
    onSettled: invalidate,
  });
  const resolve = useMutation({
    mutationFn: ({ id, resolved }: { id: string; resolved: boolean }) =>
      api.post(`${commentPath(id)}/${resolved ? "resolve" : "reopen"}`),
    onSettled: invalidate,
  });

  const inline = useMemo(() => history.comments.filter((c) => c.anchor), [history.comments]);
  const { anchorRoot, located, hits, rescan, selectionAt, takeSelection } = useInlineAnchors({
    bodyRef, bodyVersion, editing, inline, focusedId, canComment,
  });
  const [confirmDialog, confirm] = useConfirm();

  const jumpToPassage = async (row: CommentRow) => {
    floating.close();
    const request = ++navigation.current;
    const root = anchorRoot();
    if (!root || !row.anchor) return;
    const location = locateAnchor(renderedText(root), row.anchor);
    setFocusedId(row.id);
    if (location.status !== "located") { rescan(); return; }
    await revealTextOffset(root, location.start);
    if (!root.isConnected || request !== navigation.current) return;
    // Editing may have moved the quote while CodeMirror rendered its viewport.
    const current = locateAnchor(renderedText(root), row.anchor);
    if (current.status !== "located") { rescan(); return; }
    const range = rangeForOffsets(root, current.start, current.end);
    if (range) scrollRangeIntoView(range);
    rescan();
  };

  const floating = useCommentPointer(bodyRef, hits, editing, setFocusedId);
  const floatingRow = inline.find(row => row.id === floating.pointer?.id && !row.resolved_at);
  // RADD-1448: replies show unless a thread is resolved — here, the Resolved group.
  const expansion = useThreadExpansion(linkedInline?.root_id);
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  // RADD-1297: focus the linked thread (its passage lights up), show the resolved group if that
  // is where it lives, and land on it; the expansion opens it.
  const linkedRootResolved = !!linkedInline && inline.some((row) => row.id === linkedInline.root_id && row.resolved_at);
  useEffect(() => {
    if (!linkedInline) return;
    setFocusedId(linkedInline.root_id);
    if (linkedRootResolved) setShowResolved(true);
  }, [linkedInline, linkedRootResolved]);
  useLandOnComment(linkedInline?.id);
  // One composer per thread: while the popover holds a thread open, its rail card offers no Reply
  // (two editors over one draft would each overwrite the other's text).
  const pinnedId = floating.pointer?.pinned ? floating.pointer.id : null;
  const replyProps = (row: CommentRow, inPopover = false) => ({
    expansion,
    canReply: canComment && (inPopover || row.id !== pinnedId),
    draft: replyDrafts[row.id] ?? "",
    onDraft: (value: string) => setReplyDrafts(previous => ({...previous, [row.id]: value})),
  });

  // RADD-1283: the server's answer under the parent's resolution rule.
  const canResolveRow = (row: CommentRow) => !!row.can_resolve;
  // Open, Detached (passage gone or ambiguous — kept until resolved, RADD-726/1276), Resolved.
  const open = located.filter(({ row, orphaned }) => !row.resolved_at && orphaned === null);
  const detached = located.filter(({ row, orphaned }) => !row.resolved_at && orphaned !== null);
  const resolved = located.filter(({ row }) => row.resolved_at);
  const resolvableDetached = detached.filter(({ row }) => canResolveRow(row));
  const resolveAllDetached = async () => {
    const count = resolvableDetached.length;
    const ok = await confirm({
      title: "Resolve detached comments",
      message:
        count === 1
          ? "Resolve this comment? The passage it was written about is no longer on the page. It keeps its quote under Resolved."
          : `Resolve these ${count} comments? The passages they were written about are no longer on the page. They keep their quotes under Resolved.`,
      confirmLabel: count === 1 ? "Resolve it" : `Resolve ${count}`,
    });
    if (!ok) return;
    setFocusedId(null);
    for (const { row } of resolvableDetached) resolve.mutate({ id: row.id, resolved: true });
  };
  // A rail thread; a resolved one ignores the floating popover and offers Unresolve.
  const threadFor = ({ row, orphaned }: (typeof located)[number], resolvedView = false) => (
    <Thread
      key={row.id}
      {...replyProps(row)}
      row={row}
      orphaned={orphaned}
      focused={row.id === focusedId}
      canResolve={canResolveRow(row)}
      resolvedView={resolvedView}
      onFocus={() => setFocusedId(row.id)}
      onNavigate={() => jumpToPassage(row)}
      onResolve={() => {
        if (!resolvedView) setFocusedId(null);
        resolve.mutate({ id: row.id, resolved: !resolvedView });
      }}
    />
  );

  if (!inline.length && !canComment && !history.hasOlder && !history.isError && !history.isPending) return null;

  return (
    <>
      {floating.pointer && floatingRow && (
        <PageCommentPopover pointer={floating.pointer} onClose={floating.close} onKeep={floating.keep}
          onLeave={floating.leave} onPin={floating.pin}>
          {/* The hover card previews the comment; pinned (a click, or Open thread) it is the thread. */}
          <Thread row={floatingRow} orphaned={null} focused canResolve={floating.pointer.pinned && canResolveRow(floatingRow)}
            onResolve={() => {floating.close(); setFocusedId(null); resolve.mutate({id: floatingRow.id, resolved: true});}}
            preview={!floating.pointer.pinned} {...replyProps(floatingRow, true)} />
        </PageCommentPopover>
      )}
      {selectionAt && canComment && (
        <button
          type="button"
          style={{ left: selectionAt.left, top: selectionAt.top }}
          onMouseDown={(event) => {
            event.preventDefault(); // keep the selection alive
            setDraftAnchor(takeSelection());
            const pane = railRef.current?.closest<HTMLElement>("[data-page-comment-sidebar]");
            if (pane) pane.scrollTop = 0;
          }}
          className="fixed z-[60] flex items-center gap-1 rounded-md border border-strong bg-overlay px-2 py-1 text-[12px] text-fg shadow-pop cursor-pointer"
        >
          <MessageSquarePlus size={12} aria-hidden />
          Comment
        </button>
      )}

      <CommentHistory hasOlder={history.hasOlder} loading={history.loadingOlder}
        onOlder={history.loadOlder} error={history.isError ? errorMessage(history.error) : undefined}>
      <section ref={railRef} className="flex flex-col gap-2" data-inline-comment-rail>
        <h2 className="text-xs font-semibold text-heading">Inline comments ({open.length + detached.length}{history.hasOlder ? "+" : ""})</h2>
        {resolve.isError && <p role="alert" className="text-xs text-status-danger-ink">{errorMessage(resolve.error)}</p>}
        {history.isPending && <p role="status" className="text-xs text-fg-muted">Loading comments…</p>}
        {!history.isPending && !open.length && !detached.length && !draftAnchor && (
          <p className="text-xs text-fg-muted">{canComment ? "Select a passage to comment on it." : "No open inline comments."}</p>
        )}
        {draftAnchor && (
          <div className="rounded-md border border-accent bg-surface p-2">
            <p className="mb-1 text-[11px] italic text-fg-muted">“{draftAnchor.quote}”</p>
            <RichEditor
              value={draftBody}
              onChange={setDraftBody}
              placeholder="Comment on this…"
              autoFocus
              className="[&_.ProseMirror]:min-h-[3rem]"
            />
            <div className="mt-1 flex gap-2">
              <Button
                size="sm"
                disabled={!draftBody.trim() || post.isPending}
                onClick={() => post.mutate({ body: draftBody, anchor: draftAnchor })}
              >
                Comment
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDraftAnchor(null)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {open.map((entry) => threadFor(entry))}

        {detached.length > 0 && (
          <section data-detached-comments className="flex flex-col gap-2 border-t border-subtle pt-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-[11px] font-semibold text-heading">Detached ({detached.length})</h3>
              {resolvableDetached.length > 0 && (
                <Button size="sm" variant="ghost" onClick={() => void resolveAllDetached()} disabled={resolve.isPending}>
                  {resolvableDetached.length === detached.length
                    ? "Resolve all"
                    : `Resolve ${resolvableDetached.length} of ${detached.length}`}
                </Button>
              )}
            </div>
            <p className="text-[11px] text-fg-muted">
              The passages these were written about were edited away, or now appear more than
              once. They stay until someone resolves them; a resolved comment keeps its quote.
            </p>
            {detached.map((entry) => threadFor(entry))}
          </section>
        )}

        {resolved.length > 0 && (
          <div>
            <button
              type="button"
              onClick={() => setShowResolved((on) => !on)}
              className="rounded px-1 text-[11px] text-fg-muted hover:text-fg cursor-pointer"
            >
              Resolved ({resolved.length})
            </button>
            {showResolved && resolved.map((entry) => threadFor(entry, true))}
          </div>
        )}
      </section>
      </CommentHistory>
      {confirmDialog}
    </>
  );
}
