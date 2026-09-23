import { useState } from "react";
import { infiniteQueryOptions, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../../lib/api";
import { apiCommentPath, apiCommentTasksPath } from "../../lib/constants";
import { useCurrentUser } from "../../lib/hooks";
import { sendTaskToggle } from "../../lib/task-toggle";
import { Entity, entityMeta, invalidateEntities } from "../../lib/cache";
import { chronologicalComments, type CommentPage } from "../../lib/queries/comment-feed";
import { relativeTime } from "../../lib/dates";
import { CommentVisibility, type Comment } from "../../lib/types";
import { LazyRichViewer } from "../editor/LazyRichViewer";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import type { QuickAction } from "../items/quick-actions";
import { Button } from "../Button";
import { CommentHistory } from "../CommentHistory";

/**
 * The replies under one comment, on every surface (RADD-1246): an issue
 * comment, a page's discussion, an inline annotation. Fetched only when
 * opened; posted with an audience the server bounds by the thread's:
 *
 * - `internalLocked` — the thread is internal, so every reply is; the form
 *   says so and sends nothing about visibility (the server inherits);
 * - `canInternal` — the thread is public and this reader may write internal
 *   comments, so the form offers an Internal switch per reply.
 *
 * The composer is the SAME rich editor a top-level comment gets — `@` people,
 * `#` issues, `/` quick actions where there is an issue, the AI toolbar — a
 * reply is a comment, not a lesser thing (Hussein, on the first cut's textarea).
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
}: {
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
}) {
  const client = useQueryClient();
  const me = useCurrentUser();
  const [internal, setInternal] = useState(false);
  // The rich editor is uncontrolled after mount — bump to clear it after posting.
  const [composerKey, setComposerKey] = useState(0);
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
      retry: false,
    }),
  );
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
      setComposerKey((key) => key + 1);
    },
    onSettled: () => void invalidateEntities(client, Entity.comment),
  });
  const replyIsInternal = internalLocked || (canInternal && internal);
  const resolved = !!row.resolved_at;
  const send = (unresolve = false) => {
    if (draft.trim() && !post.isPending) post.mutate({ body: draft, unresolve });
  };
  return (
    <div className="mt-3 space-y-3 border-t border-subtle pt-3" data-comment-replies={row.id}>
      <CommentHistory
        hasOlder={query.hasNextPage}
        loading={query.isFetchingNextPage}
        onOlder={() => query.fetchNextPage()}
        error={query.isError ? errorMessage(query.error) : undefined}
      >
        {query.isPending && (
          <p role="status" className="text-xs text-fg-muted">
            Loading replies…
          </p>
        )}
        {query.isError && (
          <Button size="sm" variant="ghost" onClick={() => void query.refetch()}>
            Retry replies
          </Button>
        )}
        {chronologicalComments(query.data?.pages).map((reply) => {
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
              </p>
              <LazyRichViewer
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
      {canReply && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              send();
            }}
          >
            <div data-reply-composer data-composer-key={composerKey}>
              <RichEditor
                key={composerKey}
                value={draft}
                onChange={onDraft}
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
              <p role="alert" className="my-1 text-xs text-status-danger-ink">
                {errorMessage(post.error)}
              </p>
            )}
            <div className="flex items-center gap-2">
              <Button type="submit" size="sm" disabled={!draft.trim() || post.isPending}>
                {post.isPending ? "Replying…" : replyIsInternal ? "Reply internally" : "Reply"}
              </Button>
              {resolved && canResolve && (
                <Button type="button" size="sm" variant="secondary" data-reply-unresolve
                  disabled={!draft.trim() || post.isPending} onClick={() => send(true)}>
                  Reply and unresolve
                </Button>
              )}
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
            </div>
          </form>
      )}
    </div>
  );
}

/** The label of the toggle that opens a thread: what is there, or what you can do. */
export function repliesLabel(row: Comment, expanded: boolean, canReply: boolean): string {
  if (expanded) return "Hide replies";
  if (row.reply_count) return `${row.reply_count} ${row.reply_count === 1 ? "reply" : "replies"}`;
  return canReply ? "Reply" : "View thread";
}
