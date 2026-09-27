import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { infiniteQueryOptions, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Reply } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { apiCommentPath, apiCommentTasksPath } from "../../lib/constants";
import { useCurrentUser } from "../../lib/hooks";
import { sendTaskToggle } from "../../lib/task-toggle";
import { CopyCommentLink } from "./CopyCommentLink";
import { Entity, entityMeta, invalidateEntities } from "../../lib/cache";
import { chronologicalComments, type CommentPage } from "../../lib/queries/comment-feed";
import { relativeTime } from "@radd/plugin-sdk";
import { type Comment } from "../../lib/types";
import { ContentBody } from "../editor/ContentBody";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import type { QuickAction } from "../items/quick-actions";
import { Button } from "../Button";
import { CommentHistory } from "../CommentHistory";
import { CommentVisibility } from "@radd-plugin-ui/comments/visibility";
import { escapeBelongsInside } from "./escape";
import { repliesLabel } from "./ThreadResolution";

/** A second view of the same thread (the page rail and its popover, an issue and its peek) reads
 *  the replies the first one loaded; a post or a live update invalidates them either way. */
const REPLIES_STALE_MS = 60_000;

interface Expansion {
  isOpen: (row: Comment) => boolean;
  toggle: (row: Comment) => void;
}

/**
 * A comment's replies, on every surface (RADD-1246), and — given `expansion` — its whole thread
 * footer (RADD-1448): the disclosure over the replies (only when there are some), the Reply action,
 * `actions` beside them, the replies while open, and the reply composer while replying.
 *
 * Replying is an ACTION: one click opens the composer under the replies (showing them if they were
 * hidden), focused, with one primary button. Cancel or Escape closes it and keeps the draft (a
 * composer that mounts with a draft opens on it); posting closes and clears it. The audience is
 * bounded by the thread's:
 * - `internalLocked` — the thread is internal, so every reply is; the form sends nothing about
 *   visibility (the server inherits) and says so in one line;
 * - `canInternal` — the thread is public and this reader may write internal comments, so the form
 *   offers an Internal reply switch.
 * The composer is the same rich editor a top-level comment gets: a reply is a comment.
 */
export function CommentReplies({
  row,
  canReply,
  draft,
  onDraft,
  canInternal = false,
  internalLocked = false,
  onUploadImage,
  quickActions,
  canResolve = false,
  linkFor,
  linkedReplyId,
  expansion,
  actions,
}: {
  linkedReplyId?: string;
  row: Comment;
  canReply: boolean;
  draft: string;
  onDraft: (value: string) => void;
  canInternal?: boolean;
  internalLocked?: boolean;
  /** Image paste/insert → attachment URL; omit where the parent takes none. */
  onUploadImage?: (file: File) => Promise<string>;
  /** `/` actions on the issue in context; omit on pages. */
  quickActions?: QuickAction[];
  /** May reopen this thread — offers "Reply and unresolve" once it is resolved. */
  canResolve?: boolean;
  /** RADD-1297: the link that lands on one reply; omit to offer none. */
  linkFor?: (commentId: string) => string;
  /** Which comments show their replies; given, this draws the comment's thread footer too. */
  expansion?: Expansion;
  /** Footer controls after Reply (Resolve); only with `expansion`. */
  actions?: ReactNode;
}) {
  const footer = !!expansion;
  const open = expansion ? expansion.isOpen(row) : true;
  const count = row.reply_count ?? 0;
  const linkedHere = !!linkedReplyId && linkedReplyId !== row.id;
  // A reply left unsent reopens where it was written.
  const [composing, setComposing] = useState(() => canReply && !!draft);
  const root = useRef<HTMLDivElement>(null);
  const listId = useId();
  const client = useQueryClient();
  const me = useCurrentUser();
  const [internal, setInternal] = useState(false);
  const query = useInfiniteQuery(
    infiniteQueryOptions({
      queryKey: ["commentReplies", row.id],
      meta: entityMeta(Entity.comment),
      initialPageParam: null as string | null,
      queryFn: ({ pageParam, signal }) =>
        api.get<CommentPage>(`${apiCommentPath(row.id)}/replies`, {
          signal,
          query: { limit: "50", ...(pageParam ? { before: pageParam } : {}) },
        }),
      getNextPageParam: (page) => page.older_cursor ?? undefined,
      // Nothing to fetch for a comment nobody answered, or while its replies are hidden.
      enabled: open && (count !== 0 || linkedHere),
      staleTime: REPLIES_STALE_MS,
      retry: false,
    }),
  );
  const replies = chronologicalComments(query.data?.pages);
  useEffect(() => {
    if (linkedHere && !replies.some(reply => reply.id === linkedReplyId)
      && query.hasNextPage && !query.isFetching && !query.isError) void query.fetchNextPage();
  }, [linkedHere, linkedReplyId, replies, query.hasNextPage, query.isFetching, query.isError, query.fetchNextPage]);

  // Closing the composer from inside hands focus back to the Reply button that opened it.
  const returnFocus = useRef(false);
  useEffect(() => {
    if (composing || !returnFocus.current) return;
    returnFocus.current = false;
    root.current?.querySelector<HTMLElement>("[data-open-reply]")?.focus();
  }, [composing]);
  const closeComposer = () => {
    returnFocus.current = true;
    setComposing(false);
  };
  const startReply = () => {
    if (expansion && !open) expansion.toggle(row);
    // Already open: Reply takes you back to it.
    if (composing) root.current?.querySelector<HTMLElement>("[data-reply-composer] .ProseMirror")?.focus();
    else setComposing(true);
  };

  const post = useMutation({
    mutationFn: ({ body, unresolve }: { body: string; unresolve: boolean }) =>
      api.post<Comment>(`${apiCommentPath(row.id)}/replies`, {
        body,
        ...(unresolve ? { unresolve: true } : {}),
        ...(canInternal && internal ? { visibility: CommentVisibility.internal } : {}),
      }),
    onSuccess: () => {
      onDraft("");
      setInternal(false);
      closeComposer();
    },
    onSettled: () => void invalidateEntities(client, Entity.comment),
  });
  const replyIsInternal = internalLocked || (canInternal && internal);
  const resolved = !!row.resolved_at;
  const send = (unresolve = false) => {
    if (draft.trim() && !post.isPending) post.mutate({ body: draft, unresolve });
  };
  const replying = canReply && composing;
  const showList = open && (count > 0 || replies.length > 0 || linkedHere);
  const replyButton = canReply && (
    <Button variant="ghost" data-open-reply={row.id} onClick={startReply}
      aria-label={`Reply to ${row.author?.name ?? "this comment"}`}>
      <Reply size={13} aria-hidden />
      Reply
    </Button>
  );
  // The disclosure exists only when there is something to disclose.
  const toggle = !!expansion && count > 0 && (
    <Button variant="ghost" onClick={() => expansion?.toggle(row)} aria-expanded={open}
      aria-controls={listId} data-thread-toggle={row.id}>
      {open ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}
      {repliesLabel(row, open)}
    </Button>
  );
  const hasFooter = footer && (!!toggle || !!replyButton || !!actions);
  const listVisible = showList || replying || !footer;
  if (!hasFooter && !listVisible) return null;

  return (
    <div ref={root} className={footer ? "" : "mt-3 border-t border-subtle pt-3"}>
      {hasFooter && (
        <div className="-ml-2 mt-1 flex flex-wrap items-center gap-1" data-thread-footer={row.id}>
          {toggle}
          {replyButton}
          {actions}
        </div>
      )}
      {(listVisible || !!toggle) && (
        <div id={listId} hidden={!listVisible} className="mt-2 space-y-3" data-comment-replies={row.id}>
          {showList && (
            <CommentHistory
              hasOlder={query.hasNextPage}
              loading={query.isFetchingNextPage}
              onOlder={() => query.fetchNextPage()}
              error={query.isError ? errorMessage(query.error) : undefined}
            >
              {query.isPending && query.isFetching && (
                <p role="status" className="text-xs text-fg-muted">
                  Loading replies…
                </p>
              )}
              {query.isError && (
                <Button size="sm" variant="ghost" onClick={() => void query.refetch()}>
                  Retry replies
                </Button>
              )}
              {replies.map((reply) => {
                const isInternal = reply.visibility === CommentVisibility.internal;
                return (
                  <div
                    key={reply.id}
                    data-comment-id={reply.id}
                    data-reply-visibility={reply.visibility}
                    className={
                      "border-l-2 pl-2 " +
                      (isInternal ? "border-amber-400/40 bg-amber-500/5 py-1" : "border-subtle")
                    }
                  >
                    <p className="text-xs">
                      <span className="font-medium text-heading">{reply.author?.name ?? "Unknown author"}</span>{" "}
                      <span className="text-fg-faint" title={reply.created_at}>
                        {relativeTime(reply.created_at)}
                      </span>
                      {isInternal && (
                        <span className="ml-1.5 rounded bg-amber-500/15 px-1.5 py-px text-[10px] font-medium text-amber-300">
                          Internal
                        </span>
                      )}
                      {linkFor && <CopyCommentLink href={linkFor(reply.id)} className="ml-1.5 align-middle" />}
                    </p>
                    <ContentBody
                      record={reply}
                      context={{ entityType: "comment", entityId: reply.id, parent: { entityType: reply.entity_type, entityId: reply.entity_id } }}
                      canEdit={!!me && me.id === reply.author?.id}
                      text={reply.body}
                      // RADD-1296: a reply's author ticks its checklist in place.
                      onToggleTask={
                        me && reply.author?.id === me.id
                          ? async (toggle) => {
                              await sendTaskToggle(apiCommentTasksPath(reply.id), toggle, reply.body);
                              await client.invalidateQueries({ queryKey: ["commentReplies", row.id] });
                            }
                          : undefined
                      }
                    />
                  </div>
                );
              })}
            </CommentHistory>
          )}
          {!footer && !replying && replyButton}
          {replying && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                send();
              }}
              onKeyDown={(event) => {
                if (event.key !== "Escape" || escapeBelongsInside(event)) return;
                event.preventDefault();
                event.stopPropagation(); // the composer, not the popover or peek around it
                closeComposer();
              }}
              className="flex flex-col gap-2"
            >
              <div data-reply-composer>
                <RichEditor
                  value={draft}
                  onChange={onDraft}
                  autoFocus
                  placeholder={replyIsInternal ? "Write an internal reply…" : "Write a reply…"}
                  onSubmitShortcut={() => send()}
                  onUploadImage={onUploadImage}
                  quickActions={quickActions}
                  className={
                    "[&_.ProseMirror]:min-h-[4rem]" +
                    (replyIsInternal ? " !border-callout-warning-border/60 !bg-callout-warning-fill" : "")
                  }
                />
              </div>
              {post.isError && (
                <p role="alert" className="text-xs text-status-danger-ink">
                  {errorMessage(post.error)}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-2">
                {internalLocked && (
                  <span className="text-[11px] text-fg-muted" data-reply-audience="locked">
                    Replies to an internal thread are internal.
                  </span>
                )}
                {canInternal && !internalLocked && (
                  <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-fg-muted">
                    <input
                      type="checkbox"
                      checked={internal}
                      onChange={(event) => setInternal(event.target.checked)}
                      data-reply-internal
                    />
                    Internal reply
                  </label>
                )}
                <span className="ml-auto flex items-center gap-2">
                  <Button variant="ghost" onClick={closeComposer} data-reply-cancel>
                    Cancel
                  </Button>
                  {resolved && canResolve && (
                    <Button type="button" variant="secondary" data-reply-unresolve
                      disabled={!draft.trim() || post.isPending} onClick={() => send(true)}>
                      Reply and unresolve
                    </Button>
                  )}
                  <Button type="submit" disabled={!draft.trim() || post.isPending}>
                    {post.isPending ? "Replying…" : replyIsInternal ? "Reply internally" : "Reply"}
                  </Button>
                </span>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
