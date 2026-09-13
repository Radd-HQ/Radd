import { useState } from "react";
import { useMutation, useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Trash2 } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiCommentPath, apiParentCommentsPath } from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import { pageCommentFeedQuery, usersQuery } from "../../lib/queries";
import { useCurrentUser, useIsAuthenticated } from "../../lib/hooks";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import { LazyRichViewer as RichViewer } from "../editor/LazyRichViewer";
import { Avatar } from "../Avatar";
import { CommentHistory } from "../CommentHistory";
import { chronologicalComments } from "../../lib/queries/comment-feed";
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
 */
export function PageComments({ pageId, canComment }: { pageId: string; canComment: boolean }) {
  const user = useCurrentUser();
  const queryClient = useQueryClient();
  const history = useInfiniteQuery(pageCommentFeedQuery(pageId));
  const comments = chronologicalComments(history.data?.pages);
  const { data: users } = useQuery({ ...usersQuery, enabled: useIsAuthenticated() });
  const [body, setBody] = useState("");
  const [composerKey, setComposerKey] = useState(0);
  const [confirmDialog, confirm] = useConfirm();

  const invalidate = () => void invalidateEntities(queryClient, Entity.comment);

  const post = useMutation({
    mutationFn: () => api.post(apiParentCommentsPath("page", pageId), { body }),
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
    <section className="mt-6 border-t border-subtle pt-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
        <MessageSquare size={12} aria-hidden />
        Discussion
        {comments?.length ? (
          <span className="rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">
            {comments.length}
          </span>
        ) : null}
      </h3>

      <CommentHistory hasOlder={history.hasNextPage} loading={history.isFetchingNextPage}
        onOlder={() => history.fetchNextPage()} error={history.isError ? errorMessage(history.error) : undefined}>
      {history.isPending && <p role="status" className="text-xs text-fg-muted">Loading comments…</p>}
      <ul className="flex flex-col gap-4">
        {comments?.map((comment) => {
          const author = users?.find((u) => u.id === comment.author.id);
          return (
            <li data-comment-id={comment.id} key={comment.id} className="flex gap-2">
              <Avatar user={author ?? comment.author} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="flex items-baseline gap-2 text-[12px]">
                  <span className="font-medium text-heading">{comment.author.name}</span>
                  <span className="text-fg-faint" title={comment.created_at}>
                    {relativeTime(comment.created_at)}
                  </span>
                  {comment.author.id === user?.id && (
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
                  <RichViewer text={comment.body} />
                </div>
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
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => post.mutate()} disabled={!body.trim() || post.isPending}>
              {post.isPending ? "Posting…" : "Comment"}
            </Button>
            {post.isError && (
              <span className="text-xs text-red-400">{errorMessage(post.error)}</span>
            )}
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
