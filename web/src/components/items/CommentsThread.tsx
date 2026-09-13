import { useCallback, useState } from "react";
import { useMutation, useQueries, useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, MessageSquare, Pencil, Send, Trash2 } from "lucide-react";
import { ApiError, api, errorMessage } from "../../lib/api";
import { useAttachmentUploader } from "../../lib/useAttachmentUploader";
import {
  apiCannedRenderPath,
  apiCommentPath,
  apiItemCommentsPath,
  attachmentUrl,
} from "../../lib/constants";
import { useCurrentUser, usePermissions } from "../../lib/hooks";
import { Avatar } from "../Avatar";
import { PersonName } from "../PersonName";
import { cannedResponsesQuery, itemCommentFeedQuery, queryKeys, teamReferencesQuery, TEAMS_PAGE_SIZE } from "../../lib/queries";
import {
  AttachmentParentType,
  CommentVisibility,
  Permission,
  type CannedRender,
  type Comment,
  type CommentCreate,
  type CommentVisibilityValue,
  type Item,
  type Project,
} from "../../lib/types";
import { useIssueQuickActions, type QuickAction } from "./quick-actions";
import { CommentHistory } from "../CommentHistory";
import { chronologicalComments } from "../../lib/queries/comment-feed";
import { Button } from "../Button";
import { Select } from "../Select";
import { Spinner } from "../Spinner";
import { TeamAudience, CommentAudienceNames, COMMENT_TEAM_PREVIEW_SIZE } from "../teams/TeamAudience";
import { QueryError } from "../QueryError";

import type { AiRun } from "../editor/ai";
import { AiReadMenu } from "../editor/AiReadMenu";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import { LazyRichViewer as RichViewer } from "../editor/LazyRichViewer";
import { formatDateTime } from "../../lib/dates";

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
  const quickActions = useIssueQuickActions(item, project.id);
  const perms = usePermissions();
  const canReadInternal = perms.project(project, Permission.commentReadInternal);
  // Whether the user may post at all (spec 07): gate the composer up front with a note rather than
  // showing an editor that 403s on submit.
  const canComment = perms.project(project, Permission.commentWrite);
  const queryClient = useQueryClient();
  const comments = useInfiniteQuery(itemCommentFeedQuery(itemId));
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
  // A read-mode AI transform pending for the comment being opened for edit —
  // handed to the editor as its initial whole-document run.
  const [pendingAiRun, setPendingAiRun] = useState<AiRun | null>(null);
  const canManageProject = perms.project(project, Permission.projectManage);
  const uploadCommentImage = useCommentImageUploader(itemId);

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
    },
  });

  const submitComment = () => {
    const trimmed = body.trim();
    if (!trimmed) return;
    const internal = visibility === CommentVisibility.internal;
    createComment.mutate({
      body: trimmed,
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
    <div className="flex flex-col gap-3">
      {teamLabels.some(query => query.isError) && <div><QueryError label="comment team names" error={teamLabels.find(query => query.isError)?.error} /><Button size="sm" variant="ghost" onClick={() => void Promise.all(teamLabels.filter(query => query.isError).map(query => query.refetch()))}>Retry comment team names</Button></div>}
      <CommentHistory hasOlder={comments.hasNextPage} loading={comments.isFetchingNextPage}
        onOlder={() => comments.fetchNextPage()} error={comments.isFetchNextPageError ? errorMessage(comments.error) : undefined}>
      {list.length === 0 ? (
        <p className="text-xs text-fg-faint">No comments yet.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {list.map((comment) => {
            const internal = comment.visibility === CommentVisibility.internal;
            return (
              <li
                key={comment.id}
                data-comment-id={comment.id}
                className={
                  "flex gap-2.5" +
                  (internal
                    ? " -mx-2 rounded-md border border-amber-400/20 bg-amber-500/5 px-2 py-1.5"
                    : "")
                }
              >
                <Avatar user={comment.author} size="sm" className="mt-0.5" />
                <div className="group/comment min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-1.5 text-xs">
                    <PersonName user={comment.author} className="font-medium text-fg" />
                    <span className="text-fg-faint">
                      {formatDateTime(comment.created_at)}
                    </span>
                    {comment.updated_at !== comment.created_at && (
                      <span className="text-fg-faint">(edited)</span>
                    )}
                    {internal && <InternalBadge />}
                    {internal && comment.visible_to_teams.length > 0 && (
                      <span className="text-[10px] text-amber-300/80">
                        · <CommentAudienceNames ids={comment.visible_to_teams} names={teamNames} />
                      </span>
                    )}
                    {editingId !== comment.id && (
                      <span className="ml-auto flex items-center gap-1">
                        {/* Read-mode AI (spec 103 follow-up): query actions for
                            every reader; transforms only where edit is allowed. */}
                        <AiReadMenu
                          text={comment.body}
                          similar={{ seedKey: comment.id, excludeItemId: itemId }}
                          onTransform={
                            user?.id === comment.author.id || canManageProject
                              ? (run) => {
                                  setPendingAiRun(run);
                                  setEditingId(comment.id);
                                }
                              : undefined
                          }
                          label="AI actions for this comment"
                          className="opacity-0 transition-opacity group-hover/comment:opacity-100 aria-expanded:opacity-100"
                        />
                        {(user?.id === comment.author.id || canManageProject) && (
                          <CommentActions
                            comment={comment}
                            itemId={itemId}
                            onEdit={() => {
                              setPendingAiRun(null);
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
                      initialAiRun={pendingAiRun ?? undefined}
                      onDone={() => {
                        setPendingAiRun(null);
                        setEditingId(null);
                      }}
                    />
                  ) : (
                    <div className="mt-0.5">
                      <RichViewer text={comment.body} />
                    </div>
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
          {internalDraft && <TeamAudience value={visibleTeams} onChange={setVisibleTeams} />}
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
            onSubmitShortcut={submitComment}
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
          <div className="flex justify-end">
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
  initialAiRun,
  onDone,
}: {
  comment: Comment;
  itemId: string;
  quickActions: QuickAction[];
  /** From the read-mode AI menu: run this transform as soon as the editor mounts. */
  initialAiRun?: AiRun;
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
        initialAiRun={initialAiRun}
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
