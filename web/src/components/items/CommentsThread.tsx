import { EmailBody } from "../editor/EmailBody";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useThreadExpansion } from "../comments/useThreadExpansion";
import { useCallback, useState } from "react";
import { useMutation, useQueries, useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, MessageSquare, MessagesSquare, Pencil, Send, Trash2 } from "lucide-react";
import { ApiError, api, errorMessage } from "../../lib/api";
import { sendTaskToggle } from "../../lib/task-toggle";
import { useAttachmentUploader } from "../../lib/useAttachmentUploader";
import {
  apiCannedRenderPath,
  apiCommentPath,
  apiCommentTasksPath,
  apiItemCommentsPath,
  attachmentUrl,
} from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { Avatar } from "../Avatar";
import { PersonName } from "../PersonName";
import { cannedResponsesQuery, itemCommentFeedQuery, queryKeys, TEAMS_PAGE_SIZE } from "../../lib/queries";
import { AttachmentParentType, Permission, type CannedRender, type Comment, type CommentCreate, type Item } from "../../lib/types";
import { useIssueQuickActions, type QuickAction } from "./quick-actions";
import { CommentHistory } from "../CommentHistory";
import { chronologicalComments } from "../../lib/queries/comment-feed";
import { Button } from "../Button";
import { Select } from "../Select";
import { Spinner } from "../Spinner";
import { TeamAudience } from "../teams/TeamAudience";
import { CommentAudienceNames, COMMENT_TEAM_PREVIEW_SIZE, COMMENT_AUDIENCE_COPY } from "./CommentAudienceNames";
import { QueryError } from "../QueryError";
import { CommentReplies } from "../comments/CommentReplies";
import { CopyCommentLink } from "../comments/CopyCommentLink";
import { issueCommentHref, useLandOnComment, useLinkedComment } from "../../lib/comment-links";
import { ResolveThreadButton, ThreadBadge, ThreadFilter, repliesLabel, threadRuleClass } from "../comments/ThreadResolution";

import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import { formatDateTime, Slot, SlotId, type EditorTransform } from "@radd/plugin-sdk";
import { teamReferencesQuery } from "@radd-plugin-ui/teams/references";
import { CommentVisibility } from "@radd-plugin-ui/comments/visibility";
import type { CommentVisibilityValue } from "@radd-plugin-ui/comments/visibility";
import type { Project } from "@radd-plugin-ui/projects/types";

/** Upload a pasted/inserted image to the item and resolve its served URL —
 * through the storage-choice seam (spec 102); a dismissed prompt rejects, so
 * the editor insert aborts cleanly. */
function useCommentImageUploader(itemId: string) {
  const upload = useAttachmentUploader({
    entityType: AttachmentParentType.item,
    entityId: itemId,
  });
  return useCallback(
    async (file: File) => {
      const [attachment] = await upload([file]);
      return attachmentUrl(attachment.id);
    },
    [upload],
  );
}

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
  const { data: canned } = useQuery(cannedResponsesQuery());
  const list = chronologicalComments(comments.data?.pages);
  const labelIds = [...new Set(list.flatMap(comment => comment.visible_to_teams.slice(0, COMMENT_TEAM_PREVIEW_SIZE)))];
  const labelBatches: string[][] = [];
  for (let offset = 0; offset < labelIds.length; offset += TEAMS_PAGE_SIZE) labelBatches.push(labelIds.slice(offset, offset + TEAMS_PAGE_SIZE));
  const teamLabels = useQueries({ queries: labelBatches.map(ids => teamReferencesQuery(ids)) });
  const teamNames = new Map(teamLabels.flatMap(query => (query.data ?? []).map(row => [row.id, row.name] as const)));
  const [body, setBody] = useState("");
  // The rich editor is uncontrolled — bump this to remount (clear) it after posting.
  const [composerKey, setComposerKey] = useState(0);
  const [visibility, setVisibility] = useState<CommentVisibilityValue>(CommentVisibility.public);
  const [visibleTeams, setVisibleTeams] = useState<string[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  // RADD-1246: which thread is open, and each thread's unsent reply draft.
  const expansion = useThreadExpansion(linked?.root_id);
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  useLandOnComment(linked?.id);
  // A read action's transform pending for the comment being opened for edit —
  // handed to the editor as its initial whole-document run.
  const [pendingTransform, setPendingTransform] = useState<EditorTransform | null>(null);
  const canManageProject = perms.project(project, Permission.projectManage);
  const uploadCommentImage = useCommentImageUploader(itemId);
  // RADD-1296: tick a checklist box in a comment without opening its editor —
  // offered exactly where editing the comment is.
  const toggleCommentTask = async (comment: Comment, toggle: { index: number; checked: boolean }) => {
    await sendTaskToggle<Comment>(apiCommentTasksPath(comment.id), toggle, comment.body);
    await queryClient.invalidateQueries({ queryKey: queryKeys.comments(itemId) });
  };

  const createComment = useMutation({
    mutationFn: (payload: CommentCreate) =>
      api.post<Comment>(apiItemCommentsPath(itemId), payload),
    onSuccess: () => {
      setBody("");
      setComposerKey((key) => key + 1);
      setVisibility(CommentVisibility.public);
      setVisibleTeams([]);
      void queryClient.invalidateQueries({ queryKey: queryKeys.comments(itemId) });
      // comment_count lives on the item (spec 02) — refresh it too.
      void queryClient.invalidateQueries({ queryKey: queryKeys.item(itemId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.allowedTransitions(itemId) });
    },
  });

  const submitComment = (isThread = false) => {
    const trimmed = body.trim();
    if (!trimmed || createComment.isPending) return;
    const internal = visibility === CommentVisibility.internal;
    createComment.mutate({
      body: trimmed,
      is_thread: isThread,
      visibility,
      visible_to_teams: internal ? visibleTeams : [],
    });
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


  const internalDraft = canReadInternal && visibility === CommentVisibility.internal;

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
                      itemId={itemId}
                      quickActions={quickActions}
                      initialTransform={pendingTransform ?? undefined}
                      onDone={() => {
                        setPendingTransform(null);
                        setEditingId(null);
                      }}
                    />
                  ) : (
                    <div className="mt-0.5">
                      <EmailBody signature={comment.email_signature} parent={{ kind: "comment", id: comment.id }} canRestore={!!comment.author && user?.id === comment.author.id || canManageProject}
                        text={comment.body}
                        onToggleTask={
                          (!!comment.author && user?.id === comment.author.id) || canManageProject
                            ? (toggle) => toggleCommentTask(comment, toggle)
                            : undefined
                        }
                      />
                    </div>
                  )}
                  <div className="mt-1.5 flex flex-wrap items-center gap-3">
                  {user && (
                    <button
                      type="button"
                      onClick={() => expansion.toggle(comment)}
                      aria-expanded={expansion.isOpen(comment)}
                      data-thread-toggle={comment.id}
                      className="inline-flex min-h-8 items-center gap-1 rounded px-1 text-sm font-medium text-fg-secondary hover:bg-elevated hover:text-fg cursor-pointer"
                    >
                      {expansion.isOpen(comment) ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
                      {repliesLabel(comment, expansion.isOpen(comment), canComment)}
                    </button>
                  )}
                  {thread && canResolve && <ResolveThreadButton comment={comment} />}
                  </div>
                  {expansion.isOpen(comment) && (
                    <CommentReplies
                      row={comment}
                      linkedReplyId={linked?.root_id === comment.id ? linked.id : undefined}
                      canReply={canComment}
                      draft={replyDrafts[comment.id] ?? ""}
                      onDraft={(value) => setReplyDrafts((drafts) => ({ ...drafts, [comment.id]: value }))}
                      // An internal thread makes every reply internal; a public
                      // one may take an internal reply from someone who may write them.
                      internalLocked={internal}
                      canInternal={!internal && canReadInternal}
                      onUploadImage={uploadCommentImage}
                      quickActions={quickActions}
                      canResolve={thread && canResolve}
                      linkFor={(id) => issueCommentHref(item.key, id)}
                    />
                  )}
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
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submitComment();
          }}
          className="flex flex-col gap-2"
        >
          {canReadInternal && (
            <div
              role="radiogroup"
              aria-label="Comment visibility"
              className="flex gap-1 self-start rounded-md border border-subtle p-0.5"
            >
              {(
                [
                  [CommentVisibility.public, "Public reply"],
                  [CommentVisibility.internal, "Internal note"],
                ] as const
              ).map(([value, label]) => {
                const active = visibility === value;
                return (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setVisibility(value)}
                    className={
                      "rounded px-2 py-0.5 text-[11px] font-medium cursor-pointer transition-colors " +
                      "focus-visible:outline-2 focus-visible:outline-focus " +
                      (active
                        ? value === CommentVisibility.internal
                          ? "bg-amber-500/15 text-amber-300"
                          : "bg-elevated text-heading"
                        : "text-fg-muted hover:text-fg")
                    }
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}
          {internalDraft && <TeamAudience value={visibleTeams} onChange={setVisibleTeams} {...COMMENT_AUDIENCE_COPY} />}
          {(canned ?? []).length > 0 && (
            <Select
              value=""
              onChange={(picked) => {
                const response = (canned ?? []).find((row) => row.id === picked);
                if (!response) return;
                const insert = (text: string) =>
                  setBody((current) => (current ? `${current}\n${text}` : text));
                // Spec 66: {{token}} variables resolve against THIS item —
                // fall back to the raw body if the render call fails.
                api
                  .get<CannedRender>(apiCannedRenderPath(response.id), {
                    query: { item_id: itemId },
                  })
                  .then((rendered) => insert(rendered.body))
                  .catch(() => insert(response.body));
              }}
              aria-label="Insert canned response"
              size="sm"
              className="self-start"
              placeholder="Insert canned response…"
              options={(canned ?? []).map((response) => ({
                value: response.id,
                label: response.title,
              }))}
            />
          )}
          <RichEditor
            key={composerKey}
            value={body}
            onChange={setBody}
            onUploadImage={uploadCommentImage}
            placeholder={internalDraft ? "Write an internal note…" : "Write a comment…"}
            onSubmitShortcut={() => submitComment()}
            quickActions={quickActions}
            // Callout-warning tokens, computed per theme (RADD-900): the old
            // amber-950/30 wash had no light remap — a near-black brown behind
            // dark text on white. `!` stays because RichEditor appends this
            // AFTER its own border/bg classes, where stylesheet order, not
            // class order, would decide the winner.
            className={internalDraft ? "!border-callout-warning-border/60 !bg-callout-warning-fill" : ""}
          />
          {createComment.isError && (
            <p className="text-xs text-status-danger-ink">{errorMessage(createComment.error)}</p>
          )}
          <div className="flex items-center justify-end gap-2">
            <Button type="button" variant="secondary" data-start-thread
              disabled={createComment.isPending || body.trim() === ""}
              onClick={() => submitComment(true)}>
              <MessagesSquare size={13} aria-hidden />
              {internalDraft ? "Start internal thread" : "Start thread"}
            </Button>
            <Button type="submit" disabled={createComment.isPending || body.trim() === ""}>
              <Send size={13} aria-hidden />
              {createComment.isPending
                ? "Posting…"
                : internalDraft
                  ? "Post internal note"
                  : "Comment"}
            </Button>
          </div>
        </form>
      ) : (
        <p className="text-xs text-fg-faint">Sign in to comment.</p>
      )}
    </div>
  );
}


/** Hover actions on a comment row: edit (author) / delete (author or admin). */
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
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiCommentPath(comment.id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.comments(itemId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.item(itemId) });
    },
  });
  return (
    <span className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover/comment:opacity-100">
      {confirming ? (
        <>
          <button
            type="button"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            className="rounded px-1 py-0.5 text-[11px] font-medium text-red-400 hover:bg-red-500/10 cursor-pointer"
          >
            {remove.isPending ? "Deleting…" : "Confirm delete"}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded px-1 py-0.5 text-[11px] text-fg-muted hover:text-fg cursor-pointer"
          >
            Keep
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            onClick={onEdit}
            aria-label="Edit comment"
            className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg cursor-pointer"
          >
            <Pencil size={11} aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => setConfirming(true)}
            aria-label="Delete comment"
            className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-red-300 cursor-pointer"
          >
            <Trash2 size={11} aria-hidden />
          </button>
        </>
      )}
    </span>
  );
}

/** Inline comment editor (spec 37) — PATCH /comments/{id}, Cmd+Enter saves. */
function CommentEditForm({
  comment,
  itemId,
  quickActions,
  initialTransform,
  onDone,
}: {
  comment: Comment;
  itemId: string;
  quickActions: QuickAction[];
  /** From a read action: run this transform as soon as the editor mounts. */
  initialTransform?: EditorTransform;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(comment.body);
  const uploadCommentImage = useCommentImageUploader(itemId);
  const save = useMutation({
    mutationFn: () => api.patch<Comment>(apiCommentPath(comment.id), { body: draft }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.comments(itemId) });
      onDone();
    },
  });
  const submit = () => {
    if (draft.trim() && draft !== comment.body) save.mutate();
    else onDone();
  };
  return (
    <div className="mt-1 flex flex-col gap-1.5">
      <RichEditor
        value={draft}
        onChange={setDraft}
        onUploadImage={uploadCommentImage}
        autoFocus
        onSubmitShortcut={submit}
        quickActions={quickActions}
        initialTransform={initialTransform}
      />
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={submit} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        {save.isError && (
          <span className="text-xs text-red-400">{errorMessage(save.error)}</span>
        )}
      </div>
    </div>
  );
}
