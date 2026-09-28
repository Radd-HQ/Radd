import { ContentBody } from "../editor/ContentBody";
import { useThreadExpansion } from "../comments/useThreadExpansion";
import { useState } from "react";
import { useMutation, useQueries, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, MessageSquare, MessagesSquare, Pencil, Trash2 } from "lucide-react";
import { ApiError, api, errorMessage } from "../../lib/api";
import { sendTaskToggle } from "../../lib/task-toggle";
import { useImageUploader } from "../../lib/useAttachmentUploader";
import { apiCommentPath, apiCommentTasksPath } from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { Avatar } from "../Avatar";
import { PersonName } from "../PersonName";
import { itemCommentFeedQuery, queryKeys, TEAMS_PAGE_SIZE } from "../../lib/queries";
import { AttachmentParentType, Permission, type Comment, type Item } from "../../lib/types";
import { useIssueQuickActions } from "./quick-actions";
import { CommentHistory } from "../CommentHistory";
import { chronologicalComments } from "../../lib/queries/comment-feed";
import { Button } from "../Button";
import { Spinner } from "../Spinner";
import { CommentAudienceNames, COMMENT_TEAM_PREVIEW_SIZE } from "./CommentAudienceNames";
import { QueryError } from "../QueryError";
import { CommentEditForm } from "../comments/CommentEditForm";
import { CommentReplies } from "../comments/CommentReplies";
import { CopyCommentLink } from "../comments/CopyCommentLink";
import { IssueCommentComposer } from "../comments/IssueCommentComposer";
import { issueCommentHref, useLandOnComment, useLinkedComment } from "../../lib/comment-links";
import { ResolveThreadButton, ThreadBadge, ThreadFilter, threadRuleClass } from "../comments/ThreadResolution";

import { Entity, formatDateTime, IconButton, invalidateEntities, Slot, SlotId, useConfirm, type EditorTransform } from "@radd/plugin-sdk";
import { teamReferencesQuery } from "@radd-plugin-ui/teams/references";
import { CommentVisibility } from "@radd-plugin-ui/comments/visibility";
import type { Project } from "@radd-plugin-ui/projects/types";

interface CommentsThreadProps {
  item: Item;
  /** For the comment.read_internal check gating the visibility toggle (spec 07). */
  project: Project;
}

/** Amber "Internal" chip on comments only comment.read_internal holders see. */
function InternalBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-amber-400/40 bg-amber-500/10 px-1.5 py-px text-[10px] font-medium text-amber-300">
      <EyeOff size={9} aria-hidden />
      Internal
    </span>
  );
}

/**
 * Comment list + composer (`/items/{id}/comments`, spec 02).
 * Spec 07: comments carry `visibility`; the server already filters internal
 * ones out for users without comment.read_internal, and the composer only
 * offers the "Internal note" toggle to users who hold it.
 * RADD-1448: replies show under each comment unless its thread is resolved;
 * Reply is an action in the comment's footer; the composer at the foot stays
 * a row of two buttons (Comment, Start thread) until one is pressed.
 */
export function CommentsThread({ item, project }: CommentsThreadProps) {
  const itemId = item.id;
  const user = useCurrentUser();
  // `/` quick actions in comment editors act on the thread's issue.
  const [actionsRequested, setActionsRequested] = useState(false);
  const quickActions = useIssueQuickActions(item, project.id, actionsRequested);
  const perms = usePermissions();
  const canReadInternal = perms.project(project, Permission.commentReadInternal);
  // Whether the user may post at all (spec 07): gate the composer up front with a note rather than
  // showing an editor that 403s on submit.
  const canComment = perms.project(project, Permission.commentWrite);
  const queryClient = useQueryClient();
  const [unresolvedOnly, setUnresolvedOnly] = useState(false);
  // RADD-1297: `?comment=` — widen the first window through the linked
  // comment's thread, open that thread if the link is to a reply, land on it.
  const linked = useLinkedComment(itemId);
  const comments = useInfiniteQuery(itemCommentFeedQuery(itemId, unresolvedOnly, linked?.root_id));
  const list = chronologicalComments(comments.data?.pages);
  const labelIds = [...new Set(list.flatMap(comment => comment.visible_to_teams.slice(0, COMMENT_TEAM_PREVIEW_SIZE)))];
  const labelBatches: string[][] = [];
  for (let offset = 0; offset < labelIds.length; offset += TEAMS_PAGE_SIZE) labelBatches.push(labelIds.slice(offset, offset + TEAMS_PAGE_SIZE));
  const teamLabels = useQueries({ queries: labelBatches.map(ids => teamReferencesQuery(ids)) });
  const teamNames = new Map(teamLabels.flatMap(query => (query.data ?? []).map(row => [row.id, row.name] as const)));
  const [editingId, setEditingId] = useState<string | null>(null);
  // Each comment's unsaved edit: Cancel and Escape keep it, a save drops it.
  const [editDrafts, setEditDrafts] = useState<Record<string, string>>({});
  const dropEditDraft = (id: string) =>
    setEditDrafts((drafts) => {
      const next = { ...drafts };
      delete next[id];
      return next;
    });
  // RADD-1246/1448: whose replies show, and each thread's unsent reply draft.
  const expansion = useThreadExpansion(linked?.root_id);
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  useLandOnComment(linked?.id);
  // A read action's transform pending for the comment being opened for edit —
  // handed to the editor as its initial whole-document run.
  const [pendingTransform, setPendingTransform] = useState<EditorTransform | null>(null);
  const canManageProject = perms.project(project, Permission.projectManage);
  const uploadCommentImage = useImageUploader({ entityType: AttachmentParentType.item, entityId: itemId });
  // RADD-1296: tick a checklist box in a comment without opening its editor —
  // offered exactly where editing the comment is.
  const toggleCommentTask = async (comment: Comment, toggle: { index: number; checked: boolean }) => {
    await sendTaskToggle<Comment>(apiCommentTasksPath(comment.id), toggle, comment.body);
    await queryClient.invalidateQueries({ queryKey: queryKeys.comments(itemId) });
  };

  if (comments.isPending) return <Spinner label="Loading comments…" />;

  if (comments.isError && !comments.data) {
    if (comments.error instanceof ApiError && comments.error.status === 404) {
      return (
        <p className="flex items-center gap-2 rounded-md border border-dashed border-subtle px-3 py-2.5 text-xs text-fg-muted">
          <MessageSquare size={13} aria-hidden />
          This discussion is unavailable. The issue may have been removed or access may have changed.
        </p>
      );
    }
    return (
      <p className="text-xs text-red-400">
        Failed to load comments: {errorMessage(comments.error)}
      </p>
    );
  }


  return (
    <div className="flex flex-col gap-3" onFocusCapture={() => setActionsRequested(true)}>
      <ThreadFilter unresolvedOnly={unresolvedOnly} onChange={setUnresolvedOnly} />
      {teamLabels.some(query => query.isError) && <div><QueryError label="comment team names" error={teamLabels.find(query => query.isError)?.error} /><Button size="sm" variant="ghost" onClick={() => void Promise.all(teamLabels.filter(query => query.isError).map(query => query.refetch()))}>Retry comment team names</Button></div>}
      <CommentHistory hasOlder={comments.hasNextPage} loading={comments.isFetchingNextPage}
        onOlder={() => comments.fetchNextPage()} error={comments.isFetchNextPageError ? errorMessage(comments.error) : undefined}>
      {list.length === 0 ? (
        <p className="text-xs text-fg-faint">{unresolvedOnly ? "No unresolved threads visible to you." : "No comments yet."}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {list.map((comment) => {
            const internal = comment.visibility === CommentVisibility.internal;
            const thread = !!comment.is_thread;
            const canResolve = !!comment.can_resolve; // RADD-1283: the server applies the project's rule
            return (
              <li
                key={comment.id}
                data-comment-id={comment.id}
                data-thread={thread ? (comment.resolved_at ? "resolved" : "unresolved") : undefined}
                className={
                  "flex gap-2.5" +
                  (internal
                    ? " -mx-2 rounded-md border border-amber-400/20 bg-amber-500/5 px-2 py-1.5"
                    : thread
                      ? " -mx-2 rounded-md border border-subtle bg-surface px-2 py-1.5"
                      : "") +
                  threadRuleClass(comment)
                }
              >
                <Avatar user={comment.author ?? { id: "", name: "Unknown author" }} size="sm" className="mt-0.5" />
                <div className="group/comment min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-1.5 text-xs">
                    <PersonName user={comment.author ?? { id: "", name: "Unknown author" }} className="font-medium text-fg" />
                    <span className="text-fg-faint">
                      {formatDateTime(comment.created_at)}
                    </span>
                    {comment.updated_at !== comment.created_at && (
                      <span className="text-fg-faint">(edited)</span>
                    )}
                    {internal && <InternalBadge />}
                    <ThreadBadge comment={comment} />
                    {internal && comment.visible_to_teams.length > 0 && (
                      <span className="text-[10px] text-amber-300/80">
                        · <CommentAudienceNames ids={comment.visible_to_teams} names={teamNames} />
                      </span>
                    )}
                    {editingId !== comment.id && (
                      <span className="ml-auto flex items-center gap-1">
                        <CopyCommentLink
                          href={issueCommentHref(item.key, comment.id)}
                          className="opacity-0 transition-opacity group-hover/comment:opacity-100"
                        />
                        {/* Contributed read actions (RADD-1395) for every reader;
                            a transform only where edit is allowed. */}
                        <Slot
                          id={SlotId.contentReadAction}
                          text={comment.body}
                          context={{ entityType: "comment", entityId: comment.id, parent: { entityType: "item", entityId: itemId } }}
                          transform={
                            (!!comment.author && user?.id === comment.author.id) || canManageProject
                              ? (transform: EditorTransform) => {
                                  setPendingTransform(transform);
                                  setEditingId(comment.id);
                                }
                              : undefined
                          }
                          subject="this comment"
                          className="opacity-0 transition-opacity group-hover/comment:opacity-100 aria-expanded:opacity-100"
                        />
                        {((!!comment.author && user?.id === comment.author.id) || canManageProject) && (
                          <CommentActions
                            comment={comment}
                            itemId={itemId}
                            onEdit={() => {
                              setPendingTransform(null);
                              setEditingId(comment.id);
                            }}
                          />
                        )}
                      </span>
                    )}
                  </p>
                  {editingId === comment.id ? (
                    <CommentEditForm
                      comment={comment}
                      draft={editDrafts[comment.id] ?? comment.body}
                      onDraft={(value) => setEditDrafts((drafts) => ({ ...drafts, [comment.id]: value }))}
                      quickActions={quickActions}
                      onUploadImage={uploadCommentImage}
                      initialTransform={pendingTransform ?? undefined}
                      onSaved={() => {
                        void queryClient.invalidateQueries({ queryKey: queryKeys.comments(itemId) });
                        dropEditDraft(comment.id);
                        setPendingTransform(null);
                        setEditingId(null);
                      }}
                      onCancel={() => {
                        setPendingTransform(null);
                        setEditingId(null);
                      }}
                    />
                  ) : (
                    <div className="mt-0.5">
                      <ContentBody
                        record={comment}
                        context={{ entityType: "comment", entityId: comment.id, parent: { entityType: "item", entityId: itemId } }}
                        canEdit={(!!comment.author && user?.id === comment.author.id) || canManageProject}
                        text={comment.body}
                        onToggleTask={
                          (!!comment.author && user?.id === comment.author.id) || canManageProject
                            ? (toggle) => toggleCommentTask(comment, toggle)
                            : undefined
                        }
                      />
                    </div>
                  )}
                  <CommentReplies
                    row={comment}
                    expansion={expansion}
                    actions={thread && canResolve && <ResolveThreadButton comment={comment} />}
                    linkedReplyId={linked?.root_id === comment.id ? linked.id : undefined}
                    canReply={canComment}
                    draft={replyDrafts[comment.id] ?? ""}
                    onDraft={(value) => setReplyDrafts((drafts) => ({ ...drafts, [comment.id]: value }))}
                    // An internal thread makes every reply internal; a public
                    // one may take an internal reply from someone who may write them.
                    internalLocked={internal}
                    canInternal={!internal && canReadInternal}
                    canManage={canManageProject}
                    onUploadImage={uploadCommentImage}
                    quickActions={quickActions}
                    canResolve={thread && canResolve}
                    linkFor={(id) => issueCommentHref(item.key, id)}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      </CommentHistory>

      {user && !canComment ? (
        <p className="flex items-center gap-2 rounded-md border border-dashed border-subtle bg-surface/40 px-3 py-2.5 text-xs text-fg-muted">
          <EyeOff size={12} aria-hidden />
          You don't have permission to comment on this project.
        </p>
      ) : user ? (
        <IssueCommentComposer itemId={itemId} canReadInternal={canReadInternal}
          quickActions={quickActions} onUploadImage={uploadCommentImage} />
      ) : (
        <p className="text-xs text-fg-faint">Sign in to comment.</p>
      )}
    </div>
  );
}


/**
 * Hover actions on a comment row: edit (author) / delete (author or admin). Delete asks first. A
 * root that still has replies is refused by the server (RADD-1477) — so instead of sending it, the
 * dialog says what to do: delete the replies first. An ordinary comment also offers "Start thread
 * from this comment" (RADD-1478, GitHub #35): one PATCH, and it redraws as an unresolved thread with
 * its resolve controls, no reload. Shown on hover, and while one has focus.
 */
function CommentActions({
  comment,
  itemId,
  onEdit,
}: {
  comment: Comment;
  itemId: string;
  onEdit: () => void;
}) {
  const queryClient = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiCommentPath(comment.id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.comments(itemId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.item(itemId) });
    },
  });
  const startThread = useMutation({
    mutationFn: () => api.patch<Comment>(apiCommentPath(comment.id), { is_thread: true }),
    // The feed, the transitions guard and every other comment surface follow.
    onSuccess: () => invalidateEntities(queryClient, Entity.comment),
  });
  const replies = comment.reply_count ?? 0;
  const askToDelete = async () => {
    if (replies) {
      await confirm({
        title: "Delete comment",
        message: `This comment has ${replies === 1 ? "a reply" : `${replies} replies`}. Delete them first — a discussion is removed from its end, never by taking away its first line.`,
        confirmLabel: "OK",
        hideCancel: true,
      });
      return;
    }
    const ok = await confirm({
      title: "Delete comment",
      message: "Delete this comment? This cannot be undone.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate();
  };
  return (
    <span className="flex items-center gap-1 opacity-0 transition-opacity group-hover/comment:opacity-100 focus-within:opacity-100">
      {!comment.is_thread && !comment.parent_comment_id && (
        <IconButton onClick={() => startThread.mutate()} disabled={startThread.isPending}
          aria-label="Start thread from this comment" title="Start thread from this comment"
          data-start-thread-from={comment.id}>
          <MessagesSquare size={11} aria-hidden />
        </IconButton>
      )}
      <IconButton onClick={onEdit} aria-label="Edit comment" title="Edit comment">
        <Pencil size={11} aria-hidden />
      </IconButton>
      <IconButton danger onClick={() => void askToDelete()} disabled={remove.isPending}
        aria-label="Delete comment" title="Delete comment">
        <Trash2 size={11} aria-hidden />
      </IconButton>
      {remove.isError && (
        <span role="alert" className="text-[11px] text-status-danger-ink">{errorMessage(remove.error)}</span>
      )}
      {startThread.isError && (
        <span role="alert" className="text-[11px] text-status-danger-ink">{errorMessage(startThread.error)}</span>
      )}
      {confirmDialog}
    </span>
  );
}
