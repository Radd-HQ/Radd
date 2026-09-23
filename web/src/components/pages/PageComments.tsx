import { useState } from "react";
import { useMutation, useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { CommentReplies, repliesLabel } from "../comments/CommentReplies";
import { ResolveThreadButton, ThreadBadge, ThreadFilter, threadRuleClass } from "../comments/ThreadResolution";
import { MessageSquare, MessagesSquare, Send, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiCommentPath, apiCommentTasksPath, apiParentCommentsPath } from "../../lib/constants";
import { sendTaskToggle } from "../../lib/task-toggle";
import { relativeTime } from "../../lib/dates";
import { pageCommentFeedQuery, usersQuery } from "../../lib/queries";
import { useCurrentUser, useIsAuthenticated } from "../../lib/hooks";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import { LazyRichViewer as RichViewer } from "../editor/LazyRichViewer";
import { Avatar } from "../Avatar";
import { CommentHistory } from "../CommentHistory";
import { chronologicalComments, CommentSection } from "../../lib/queries/comment-feed";
import { Button } from "../Button";
import { useConfirm } from "../ConfirmDialog";

/**
 * A page's discussion (RADD-717).
 *
 * Deliberately NOT `CommentsThread`. That component is item-shaped end to end —
 * project-scoped permissions, issue `/` quick actions, canned service-desk
 * responses, internal-visibility team pickers — and none of it means anything on
 * a wiki page. Sharing it would have meant threading "is there a project?"
 * through every one of those, to arrive at a component that renders none of them
 * here. The two share what actually matters: the same comments table, the same
 * editor, the same mention tokens, the same notifications.
 *
 * Page comments are public only. Internal visibility is a service-desk concept
 * that exists to hide a comment from a REQUESTER, and a page has no requester.
 *
 * RADD-1283: resolvable threads work here as on an issue — Start thread, the
 * status chip and rule, Resolve/Unresolve, Reply and unresolve, and the
 * Unresolved filter — sharing `comments/ThreadResolution`. Who may resolve is
 * the server's `can_resolve`; a page has no project rule, so it is the default.
 */
export function PageComments({ pageId, canComment }: { pageId: string; canComment: boolean }) {
  const user = useCurrentUser();
  const queryClient = useQueryClient();
  const [unresolvedOnly, setUnresolvedOnly] = useState(false);
  const history = useInfiniteQuery(pageCommentFeedQuery(pageId, CommentSection.discussion, unresolvedOnly));
  const comments = chronologicalComments(history.data?.pages);
  const { data: users } = useQuery({ ...usersQuery, enabled: useIsAuthenticated() });
  const [body, setBody] = useState("");
  const [composerKey, setComposerKey] = useState(0);
  const [confirmDialog, confirm] = useConfirm();
  // RADD-1246: a discussion comment is a thread like an annotation is.
  const [openThread, setOpenThread] = useState<string | null>(null);
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});

  const invalidate = () => void invalidateEntities(queryClient, Entity.comment);

  const post = useMutation({
    mutationFn: (isThread: boolean) => api.post(apiParentCommentsPath("page", pageId), { body, is_thread: isThread }),
    onSuccess: () => {
      setBody("");
      setComposerKey((key) => key + 1); // the editor is uncontrolled — remount to clear
    },
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(apiCommentPath(id)),
    onSettled: invalidate,
  });

  return (
    <section className="mt-6 border-t border-subtle pt-4" data-page-discussion>
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <MessageSquare size={12} aria-hidden />
        Discussion
        {comments?.length ? (
          <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
            {comments.length}
          </span>
        ) : null}
      </h3>
      <div className="mb-3 flex">
        <ThreadFilter unresolvedOnly={unresolvedOnly} onChange={setUnresolvedOnly} />
      </div>

      <CommentHistory hasOlder={history.hasNextPage} loading={history.isFetchingNextPage}
        onOlder={() => history.fetchNextPage()} error={history.isError ? errorMessage(history.error) : undefined}>
      {history.isPending && <p role="status" className="text-xs text-fg-muted">Loading comments…</p>}
      {!history.isPending && comments.length === 0 && (
        <p className="text-xs text-fg-faint">
          {unresolvedOnly ? "No unresolved threads visible to you." : "No comments yet."}
        </p>
      )}
      <ul className="flex flex-col gap-4">
        {comments?.map((comment) => {
          const author = users?.find((u) => u.id === comment.author?.id);
          return (
            <li data-comment-id={comment.id} key={comment.id}
              data-thread={comment.is_thread ? (comment.resolved_at ? "resolved" : "unresolved") : undefined}
              className={"flex gap-2" + (comment.is_thread
                ? " -mx-2 rounded-md border border-subtle bg-surface px-2 py-1.5" + threadRuleClass(comment) : "")}>
              <Avatar user={author ?? comment.author ?? { id: "", name: "Unknown author" }} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="flex items-baseline gap-2 text-[12px]">
                  <span className="font-medium text-heading">{comment.author?.name ?? "Unknown author"}</span>
                  <span className="text-fg-faint" title={comment.created_at}>
                    {relativeTime(comment.created_at)}
                  </span>
                  <ThreadBadge comment={comment} />
                  {(!!comment.author && comment.author.id === user?.id) && (
                    <button
                      type="button"
                      onClick={() =>
                        void confirm({
                          title: "Delete comment",
                          message: "Delete this comment?",
                          confirmLabel: "Delete",
                          danger: true,
                        }).then((ok) => ok && remove.mutate(comment.id))
                      }
                      aria-label="Delete comment"
                      className="ml-auto rounded p-0.5 text-fg-faint hover:text-red-400 cursor-pointer"
                    >
                      <Trash2 size={11} aria-hidden />
                    </button>
                  )}
                </p>
                <div className="mt-0.5 rounded-md border border-subtle bg-surface px-2 py-1">
                  <RichViewer
                    text={comment.body}
                    // RADD-1296: the author ticks their own checklist in place.
                    onToggleTask={
                      comment.author && comment.author.id === user?.id
                        ? async (toggle) => {
                            await sendTaskToggle(apiCommentTasksPath(comment.id), toggle, comment.body);
                            await invalidateEntities(queryClient, Entity.comment);
                          }
                        : undefined
                    }
                  />
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-3">
                  {user && (
                    <button
                      type="button"
                      onClick={() => setOpenThread(openThread === comment.id ? null : comment.id)}
                      aria-expanded={openThread === comment.id}
                      data-thread-toggle={comment.id}
                      className="text-xs text-fg-muted hover:text-fg hover:underline cursor-pointer"
                    >
                      {repliesLabel(comment, openThread === comment.id, canComment)}
                    </button>
                  )}
                  {comment.can_resolve && <ResolveThreadButton comment={comment} />}
                </div>
                {openThread === comment.id && (
                  <CommentReplies
                    row={comment}
                    canReply={canComment}
                    draft={replyDrafts[comment.id] ?? ""}
                    onDraft={(value) => setReplyDrafts((drafts) => ({ ...drafts, [comment.id]: value }))}
                    canResolve={!!comment.can_resolve}
                  />
                )}
              </div>
            </li>
          );
        })}
      </ul>
      </CommentHistory>

      {canComment ? (
        <div className="mt-4 flex flex-col gap-2">
          <RichEditor
            key={composerKey}
            value={body}
            onChange={setBody}
            placeholder="Add to the discussion…"
            className="[&_.ProseMirror]:min-h-[5rem]"
          />
          <div className="flex items-center justify-end gap-2">
            {post.isError && (
              <span className="mr-auto text-xs text-status-danger-ink">{errorMessage(post.error)}</span>
            )}
            <Button size="sm" variant="secondary" data-start-thread
              onClick={() => post.mutate(true)} disabled={!body.trim() || post.isPending}>
              <MessagesSquare size={13} aria-hidden />
              Start thread
            </Button>
            <Button size="sm" onClick={() => post.mutate(false)} disabled={!body.trim() || post.isPending}>
              <Send size={13} aria-hidden />
              {post.isPending ? "Posting…" : "Comment"}
            </Button>
          </div>
        </div>
      ) : (
        // Disable up front rather than let the post 403 (the house rule).
        <p className="mt-4 text-[13px] text-fg-faint">
          You don't have permission to comment on pages.
        </p>
      )}
      {confirmDialog}
    </section>
  );
}
