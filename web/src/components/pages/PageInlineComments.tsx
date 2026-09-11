import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Check, MessageSquarePlus, RotateCcw, Unlink } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiCommentPath, apiParentCommentsPath } from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import { pageCommentFeedQuery } from "../../lib/queries";
import type { Comment } from "../../lib/types";
import { useCurrentUser } from "../../lib/hooks";
import { makeAnchor, orderByAnchor, type TextAnchor } from "../../lib/anchoring";
import { offsetsForSelection, rangeForOffsets, renderedText } from "../../lib/dom-text";
import { LazyRichViewer as RichViewer } from "../editor/LazyRichViewer";
import { CommentHistory } from "../CommentHistory";
import { chronologicalComments, CommentSection } from "../../lib/queries/comment-feed";
import { Button } from "../Button";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";

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
  canComment,
}: {
  pageId: string;
  /** The element the page body renders into — the anchors' coordinate space. */
  bodyRef: React.RefObject<HTMLElement | null>;
  /** Bump to re-scan after the body re-renders (a save, a lazy segment). */
  bodyVersion: number;
  canComment: boolean;
}) {
  const user = useCurrentUser();
  const queryClient = useQueryClient();
  const history = useInfiniteQuery(pageCommentFeedQuery(pageId, CommentSection.inline));
  const data = history.data;
  const [draftAnchor, setDraftAnchor] = useState<TextAnchor | null>(null);
  const [draftBody, setDraftBody] = useState("");
  const [selectionAt, setSelectionAt] = useState<{ left: number; top: number } | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const pendingSelection = useRef<TextAnchor | null>(null);

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
    { row: Comment; start: number | null }[]
  >([]);

  const rescan = useCallback(() => {
    const root = bodyRef.current;
    if (!root) return;
    const text = renderedText(root);
    const ordered = orderByAnchor(text, inline);
    setLocated(
      ordered.map(({ row, location }) => ({
        row,
        start: location?.status === "located" ? location.start : null,
      })),
    );

    // Paint. Resolved threads leave the highlight layer as well as the rail.
    if (typeof CSS === "undefined" || !("highlights" in CSS)) return;
    const open: Range[] = [];
    const focused: Range[] = [];
    for (const { row, location } of ordered) {
      if (row.resolved_at || location?.status !== "located") continue;
      const range = rangeForOffsets(root, location.start, location.end);
      if (!range) continue;
      (row.id === focusedId ? focused : open).push(range);
    }
    CSS.highlights.set(HIGHLIGHT, new Highlight(...open));
    CSS.highlights.set(HIGHLIGHT_FOCUS, new Highlight(...focused));
  }, [bodyRef, inline, focusedId]);

  useEffect(() => {
    rescan();
    return () => {
      if (typeof CSS !== "undefined" && "highlights" in CSS) {
        CSS.highlights.delete(HIGHLIGHT);
        CSS.highlights.delete(HIGHLIGHT_FOCUS);
      }
    };
  }, [rescan, bodyVersion]);

  // RADD-731: select text in the body, comment on it.
  useEffect(() => {
    const root = bodyRef.current;
    if (!root || !canComment) return;
    const onUp = () => {
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
  }, [bodyRef, canComment]);

  const open = located.filter(({ row }) => !row.resolved_at);
  const resolved = located.filter(({ row }) => row.resolved_at);
  const orphans = open.filter(({ start }) => start === null);

  if (!inline.length && !canComment && !history.hasNextPage && !history.isError && !history.isPending) return null;

  return (
    <>
      {selectionAt && canComment && (
        <button
          type="button"
          style={{ left: selectionAt.left, top: selectionAt.top }}
          onMouseDown={(event) => {
            event.preventDefault(); // keep the selection alive
            setDraftAnchor(pendingSelection.current);
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
      <aside className="mt-4 flex flex-col gap-2" data-inline-comment-rail>
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

        {open.map(({ row, start }) => (
          <Thread
            key={row.id}
            row={row}
            orphaned={start === null}
            focused={row.id === focusedId}
            canResolve={canComment || row.author.id === user?.id}
            onFocus={() => setFocusedId(row.id)}
            onResolve={() => resolve.mutate({ id: row.id, resolved: true })}
          />
        ))}

        {orphans.length > 0 && (
          <p className="px-1 text-[11px] text-fg-faint">
            {orphans.length} comment{orphans.length === 1 ? "" : "s"} above no longer match the
            page text — the passage was edited or removed.
          </p>
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
              resolved.map(({ row }) => (
                <Thread
                  key={row.id}
                  row={row}
                  orphaned={false}
                  focused={false}
                  canResolve={canComment || row.author.id === user?.id}
                  resolvedView
                  onFocus={() => setFocusedId(row.id)}
                  onResolve={() => resolve.mutate({ id: row.id, resolved: false })}
                />
              ))}
          </div>
        )}
      </aside>
      </CommentHistory>
    </>
  );
}

function Thread({
  row,
  orphaned,
  focused,
  canResolve,
  resolvedView = false,
  onFocus,
  onResolve,
}: {
  row: Comment;
  orphaned: boolean;
  focused: boolean;
  canResolve: boolean;
  resolvedView?: boolean;
  onFocus: () => void;
  onResolve: () => void;
}) {
  return (
    <div
      data-thread
      data-comment-id={row.id}
      data-orphaned={orphaned || undefined}
      onMouseEnter={onFocus}
      className={
        "rounded-md border bg-surface p-2 " +
        (focused ? "border-strong" : "border-subtle") +
        (resolvedView ? " opacity-70" : "")
      }
    >
      <p className="mb-1 flex items-center gap-1 text-[11px] italic text-fg-muted">
        {orphaned && <Unlink size={10} aria-hidden className="shrink-0" />}
        “{row.anchor?.quote}”
      </p>
      <p className="text-[12px]">
        <span className="font-medium text-heading">{row.author.name}</span>{" "}
        <span className="text-fg-faint" title={row.created_at}>
          {relativeTime(row.created_at)}
        </span>
      </p>
      <div className="mt-0.5">
        <RichViewer text={row.body} />
      </div>
      {canResolve && (
        <button
          type="button"
          onClick={onResolve}
          className="mt-1 flex items-center gap-1 rounded px-1 text-[11px] text-fg-muted hover:text-fg cursor-pointer"
        >
          {resolvedView ? <RotateCcw size={10} aria-hidden /> : <Check size={10} aria-hidden />}
          {resolvedView ? "Reopen" : "Resolve"}
        </button>
      )}
    </div>
  );
}
