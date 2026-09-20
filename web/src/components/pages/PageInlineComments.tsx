import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiCommentPath, apiParentCommentsPath } from "../../lib/constants";
import { pageCommentFeedQuery } from "../../lib/queries";
import type { Comment } from "../../lib/types";
import { useCurrentUser } from "../../lib/hooks";
import { locateAnchor, makeAnchor, orderByAnchor, type AnchorLocation, type TextAnchor } from "../../lib/anchoring";
import { offsetsForSelection, rangeForOffsets, renderedText, revealTextOffset, scrollRangeIntoView } from "../../lib/dom-text";
import { CommentHistory } from "../CommentHistory";
import { chronologicalComments, CommentSection } from "../../lib/queries/comment-feed";
import { Button } from "../Button";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";

import { PageCommentThread as Thread, type OrphanReason } from "./PageCommentThread";
import { useConfirm } from "../ConfirmDialog";
import { PageCommentPopover } from "./PageCommentPopover";
import { useCommentPointer, type CommentHit } from "./useCommentPointer";

const HIGHLIGHT = "radd-inline-comment";
const HIGHLIGHT_FOCUS = "radd-inline-comment-focus";

/**
 * Inline, anchored, resolvable comments on a page (RADD-726).
 *
 * **Highlighting uses the CSS Custom Highlight API**, not wrapped `<mark>`
 * elements. The body is rendered by Crepe/ProseMirror, which owns that DOM and
 * reconciles it; inserting elements into it invites the editor to fight back or
 * to serialise our markup into the document. `CSS.highlights` paints ranges
 * without touching the tree at all, so ProseMirror never knows. Where it is
 * unsupported the comments still work — the rail, the threads and resolving are
 * all unaffected — only the tint is missing, which is the right thing to lose.
 *
 * Anchors resolve against the RENDERED text (see `lib/dom-text.ts`): the quote
 * in a comment should be the words someone selected, not markdown source they
 * never saw.
 */
export function PageInlineComments({
  pageId,
  bodyRef,
  bodyVersion,
  editing = false,
  canComment,
  canManage = false,
}: {
  pageId: string;
  /** The element the page body renders into — the anchors' coordinate space. */
  bodyRef: React.RefObject<HTMLElement | null>;
  /** Bump to re-scan after the body re-renders (a save, a lazy segment). */
  bodyVersion: number;
  editing?: boolean;
  canComment: boolean;
  canManage?: boolean;
}) {
  const user = useCurrentUser();
  const queryClient = useQueryClient();
  const history = useInfiniteQuery(pageCommentFeedQuery(pageId, CommentSection.inline));
  const data = history.data;
  const [draftAnchor, setDraftAnchor] = useState<TextAnchor | null>(null);
  const [draftBody, setDraftBody] = useState("");
  const [selectionAt, setSelectionAt] = useState<{ left: number; top: number } | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const focusedIdRef = useRef(focusedId);
  focusedIdRef.current = focusedId;
  const navigation = useRef(0);
  const hits = useRef<CommentHit[]>([]);
  const [showResolved, setShowResolved] = useState(false);
  const pendingSelection = useRef<TextAnchor | null>(null);
  const railRef = useRef<HTMLElement>(null);
  // Exclude editor toolbars and page controls from the anchor coordinate space.
  const anchorRoot = useCallback(() => {
    const host = bodyRef.current;
    return host?.querySelector<HTMLElement>("[data-page-body]")
      ?? host?.querySelector<HTMLElement>(".ProseMirror") ?? host;
  }, [bodyRef]);

  const invalidate = () => void invalidateEntities(queryClient, Entity.comment);
  const post = useMutation({
    mutationFn: (payload: { body: string; anchor: TextAnchor }) =>
      api.post(apiParentCommentsPath("page", pageId), payload),
    onSuccess: () => {
      setDraftAnchor(null);
      setDraftBody("");
    },
    onSettled: invalidate,
  });
  const resolve = useMutation({
    mutationFn: ({ id, resolved }: { id: string; resolved: boolean }) =>
      api.post(`${apiCommentPath(id)}/${resolved ? "resolve" : "reopen"}`),
    onSettled: invalidate,
  });

  const inline = useMemo(
    () => chronologicalComments(data?.pages).filter((c) => c.anchor),
    [data],
  );

  // Locate every anchor against the current rendered text, in document order.
  const [located, setLocated] = useState<
    { row: Comment; start: number | null; orphaned: OrphanReason | null }[]
  >([]);
  const [confirmDialog, confirm] = useConfirm();

  const rescan = useCallback(() => {
    const root = anchorRoot();
    if (!root) return;
    const text = renderedText(root);
    const ordered = orderByAnchor(text, inline);
    setLocated(
      ordered.map(({ row, location }) => ({
        row,
        start: location?.status === "located" ? location.start : null,
        orphaned: orphanReason(location),
      })),
    );

    // Cache visible ranges for pointer hit testing as well as highlighting.
    hits.current = [];
    const open: Range[] = [];
    const focused: Range[] = [];
    for (const { row, location } of ordered) {
      if ((row.resolved_at && row.id !== focusedIdRef.current) || location?.status !== "located") continue;
      const range = rangeForOffsets(root, location.start, location.end);
      if (!range) continue;
      if (!row.resolved_at) hits.current.push({id: row.id, range});
      (row.id === focusedIdRef.current ? focused : open).push(range);
    }
    if (typeof CSS === "undefined" || !("highlights" in CSS)) return;
    CSS.highlights.set(HIGHLIGHT, new Highlight(...open));
    CSS.highlights.set(HIGHLIGHT_FOCUS, new Highlight(...focused));
  }, [anchorRoot, inline, focusedId]);

  useEffect(() => {
    rescan();
    let frame = 0;
    const observer = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(rescan);
    });
    if (bodyRef.current) observer.observe(bodyRef.current, {subtree: true, childList: true, characterData: true});
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      if (typeof CSS !== "undefined" && "highlights" in CSS) {
        CSS.highlights.delete(HIGHLIGHT);
        CSS.highlights.delete(HIGHLIGHT_FOCUS);
      }
    };
  }, [rescan, bodyVersion, bodyRef, editing]);

  // RADD-731: select text in the body, comment on it.
  useEffect(() => {
    const root = anchorRoot();
    if (!root || !canComment) return;
    const onUp = () => {
      const root = anchorRoot();
      if (!root) return;
      const offsets = offsetsForSelection(root);
      if (!offsets) {
        setSelectionAt(null);
        return;
      }
      const text = renderedText(root);
      pendingSelection.current = makeAnchor(text, offsets.start, offsets.end);
      const rect = window.getSelection()?.getRangeAt(0).getBoundingClientRect();
      if (rect) setSelectionAt({ left: rect.left, top: rect.bottom + 6 });
    };
    document.addEventListener("mouseup", onUp);
    return () => document.removeEventListener("mouseup", onUp);
  }, [anchorRoot, canComment, bodyVersion, editing]);

  const jumpToPassage = async (row: Comment) => {
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
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const replyProps = (row: Comment) => ({
    canReply: canComment,
    draft: replyDrafts[row.id] ?? "",
    onDraft: (value: string) => setReplyDrafts(previous => ({...previous, [row.id]: value})),
  });

  const canResolveRow = (row: Comment) => canManage || (canComment && row.author?.id === user?.id);
  // RADD-1276: three groups. Open comments that still point at the page, the
  // ones whose passage is gone (a rewrite strands all of them at once — they
  // stay, by RADD-726, until someone resolves them, so they get a place, a
  // label and one action), and the resolved ones.
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

  if (!inline.length && !canComment && !history.hasNextPage && !history.isError && !history.isPending) return null;

  return (
    <>
      {floating.pointer && floatingRow && (
        <PageCommentPopover pointer={floating.pointer} onClose={floating.close} onKeep={floating.keep}
          onLeave={floating.leave} onPin={floating.pin}>
          <Thread row={floatingRow} orphaned={null} focused canResolve={floating.pointer.pinned && (canManage || (canComment && floatingRow.author?.id === user?.id))}
            onResolve={() => {floating.close(); setFocusedId(null); resolve.mutate({id: floatingRow.id, resolved: true});}}
            expanded={floating.pointer.pinned} onToggle={floating.pointer.pinned ? floating.close : floating.pin} {...replyProps(floatingRow)} />
        </PageCommentPopover>
      )}
      {selectionAt && canComment && (
        <button
          type="button"
          style={{ left: selectionAt.left, top: selectionAt.top }}
          onMouseDown={(event) => {
            event.preventDefault(); // keep the selection alive
            setDraftAnchor(pendingSelection.current);
            const pane = railRef.current?.closest<HTMLElement>("[data-page-comment-sidebar]");
            if (pane) pane.scrollTop = 0;
            setSelectionAt(null);
          }}
          className="fixed z-[60] flex items-center gap-1 rounded-md border border-strong bg-overlay px-2 py-1 text-[12px] text-fg shadow-pop cursor-pointer"
        >
          <MessageSquarePlus size={12} aria-hidden />
          Comment
        </button>
      )}

      <CommentHistory hasOlder={history.hasNextPage} loading={history.isFetchingNextPage}
        onOlder={() => history.fetchNextPage()} error={history.isError ? errorMessage(history.error) : undefined}>
      <section ref={railRef} className="flex flex-col gap-2" data-inline-comment-rail>
        <h2 className="text-xs font-semibold text-heading">Inline comments ({open.length + detached.length}{history.hasNextPage ? "+" : ""})</h2>
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

        {open.map(({ row }) => (
          <Thread
            key={row.id}
            expanded={expandedId === row.id && !floating.pointer?.pinned}
            onToggle={() => {floating.close(); setExpandedId(expandedId === row.id ? null : row.id);}}
            {...replyProps(row)}
            row={row}
            orphaned={null}
            focused={row.id === focusedId}
            canResolve={canResolveRow(row)}
            onFocus={() => setFocusedId(row.id)}
            onNavigate={() => jumpToPassage(row)}
            onResolve={() => {
              setFocusedId(null);
              resolve.mutate({ id: row.id, resolved: true });
            }}
          />
        ))}

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
            {detached.map(({ row, orphaned }) => (
              <Thread
                key={row.id}
                expanded={expandedId === row.id && !floating.pointer?.pinned}
                onToggle={() => {floating.close(); setExpandedId(expandedId === row.id ? null : row.id);}}
                {...replyProps(row)}
                row={row}
                orphaned={orphaned}
                focused={row.id === focusedId}
                canResolve={canResolveRow(row)}
                onFocus={() => setFocusedId(row.id)}
                onNavigate={() => jumpToPassage(row)}
                onResolve={() => {
                  setFocusedId(null);
                  resolve.mutate({ id: row.id, resolved: true });
                }}
              />
            ))}
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
            {showResolved &&
              resolved.map(({ row, orphaned }) => (
                <Thread
                  key={row.id}
                  expanded={expandedId === row.id}
                  onToggle={() => setExpandedId(expandedId === row.id ? null : row.id)}
                  {...replyProps(row)}
                  row={row}
                  orphaned={orphaned}
                  focused={row.id === focusedId}
                  canResolve={canResolveRow(row)}
                  resolvedView
                  onFocus={() => setFocusedId(row.id)}
                  onNavigate={() => jumpToPassage(row)}
                  onResolve={() => resolve.mutate({ id: row.id, resolved: false })}
                />
              ))}
          </div>
        )}
      </section>
      </CommentHistory>
      {confirmDialog}
    </>
  );
}

/** The rail's word for a location that is not "located" — null when it is. */
function orphanReason(location: AnchorLocation | null): OrphanReason | null {
  if (!location || location.status === "located") return null;
  return location.status === "ambiguous" ? "ambiguous" : "removed";
}
