import { MessageSquare, Trash2 } from "lucide-react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Avatar, CommentComposer, CommentComposerMode, CommentHistory, CommentReplies, CommentSection, CopyCommentLink,
  IconButton, ResolveThreadButton, RichEditor, RichViewer, ThreadBadge, ThreadFilter, api, commentHref, errorMessage,
  invalidateEntities, relativeTime, threadRuleClass, useCommentFeed, useConfirm, useCurrentUser, useIsAuthenticated,
  useLandOnComment, useLinkedComment, useThreadExpansion, type CommentComposerModeValue, Entity } from "@radd/plugin-sdk";
import { commentPath, pageCommentsPath } from "../endpoints";
import { ownTaskToggle } from "./PageCommentThread";
import { usePeople } from "./people";

/**
 * A page's discussion (RADD-717). Not `CommentsThread`: that component is item-shaped (project
 * permissions, `/` actions, canned responses, internal visibility), none of which a page has.
 * Page comments are public only — internal visibility hides a comment from a REQUESTER, and a page
 * has none. Resolvable threads as on an issue; who may resolve is the server's `can_resolve`.
 * RADD-1448: the issue's model — replies show unless a thread is resolved, Reply is an action in
 * each comment's footer, and the composer is a Comment / Start thread row until one is pressed.
 */
export function PageComments({ pageId, canComment }: { pageId: string; canComment: boolean }) {
  const user = useCurrentUser();
  const queryClient = useQueryClient();
  const [unresolvedOnly, setUnresolvedOnly] = useState(false);
  // RADD-1297: a link to a discussion comment widens the feed through it.
  const linked = useLinkedComment(pageId);
  const linkedDiscussion = linked && !linked.anchored ? linked : null;
  const history = useCommentFeed({
    parentType: "page", parentId: pageId, section: CommentSection.discussion, unresolvedOnly,
    through: linkedDiscussion?.root_id,
  });
  const comments = history.comments;
  const users = usePeople(useIsAuthenticated());
  const [body, setBody] = useState("");
  const [mode, setMode] = useState<CommentComposerModeValue | null>(null);
  const [confirmDialog, confirm] = useConfirm();
  // RADD-1246: a discussion comment is a thread like an annotation is.
  const expansion = useThreadExpansion(linkedDiscussion?.root_id);
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  useLandOnComment(linkedDiscussion?.id);

  const invalidate = () => void invalidateEntities(queryClient, Entity.comment);

  const post = useMutation({
    mutationFn: (isThread: boolean) => api.post(pageCommentsPath(pageId), { body, is_thread: isThread }),
    onSuccess: () => {
      setBody("");
      setMode(null);
    },
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<void>(commentPath(id)),
    onSettled: invalidate,
  });
  const thread = mode === CommentComposerMode.thread;

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

      <CommentHistory hasOlder={history.hasOlder} loading={history.loadingOlder}
        onOlder={history.loadOlder} error={history.isError ? errorMessage(history.error) : undefined}>
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
                  <CopyCommentLink href={commentHref(comment.id)} className="ml-auto" />
                  {(!!comment.author && comment.author.id === user?.id) && (
                    <IconButton
                      danger
                      onClick={() =>
                        void confirm({
                          title: "Delete comment",
                          // Deleting a root removes its replies too.
                          message: comment.reply_count
                            ? `Delete this comment and its ${comment.reply_count === 1 ? "reply" : `${comment.reply_count} replies`}?`
                            : "Delete this comment?",
                          confirmLabel: "Delete",
                          danger: true,
                        }).then((ok) => ok && remove.mutate(comment.id))
                      }
                      aria-label="Delete comment"
                      title="Delete comment"
                    >
                      <Trash2 size={11} aria-hidden />
                    </IconButton>
                  )}
                </p>
                <div className="mt-0.5 rounded-md border border-subtle bg-surface px-2 py-1">
                  <RichViewer text={comment.body} onToggleTask={ownTaskToggle(comment, user?.id, queryClient)} />
                </div>
                <CommentReplies
                  row={comment}
                  expansion={expansion}
                  actions={comment.can_resolve && <ResolveThreadButton comment={comment} />}
                  linkedReplyId={linkedDiscussion?.root_id === comment.id ? linkedDiscussion.id : undefined}
                  canReply={canComment}
                  draft={replyDrafts[comment.id] ?? ""}
                  onDraft={(value) => setReplyDrafts((drafts) => ({ ...drafts, [comment.id]: value }))}
                  canResolve={!!comment.can_resolve}
                  linkFor={commentHref}
                />
              </div>
            </li>
          );
        })}
      </ul>
      </CommentHistory>

      {canComment ? (
        <div className="mt-4">
          <CommentComposer
            mode={mode}
            onMode={(next) => {
              post.reset();
              setMode(next);
            }}
            submitLabel={thread ? "Start thread" : "Comment"}
            canSubmit={!!body.trim()}
            pending={post.isPending}
            error={post.isError ? errorMessage(post.error) : undefined}
            onSubmit={() => post.mutate(thread)}
          >
            <RichEditor
              value={body}
              onChange={setBody}
              autoFocus
              placeholder={thread ? "Start a thread…" : "Add to the discussion…"}
              className="[&_.ProseMirror]:min-h-[5rem]"
            />
          </CommentComposer>
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
