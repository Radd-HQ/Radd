import { Check, RotateCcw, Unlink } from "lucide-react";
import { relativeTime } from "../../lib/dates";
import type { Comment } from "../../lib/types";
import { LazyRichViewer as RichViewer } from "../editor/LazyRichViewer";
import { useQueryClient } from "@tanstack/react-query";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiCommentTasksPath } from "../../lib/constants";
import { useCurrentUser } from "../../lib/hooks";
import { sendTaskToggle } from "../../lib/task-toggle";
import { commentHref } from "../../lib/comment-links";
import { CopyCommentLink } from "../comments/CopyCommentLink";
import { CommentReplies, repliesLabel } from "../comments/CommentReplies";

/** Why a comment no longer points at the page (RADD-1276): its passage was
 *  edited away, or now appears more than once and the context cannot choose. */
export type OrphanReason = "removed" | "ambiguous";

const ORPHAN_LABEL: Record<OrphanReason, string> = {
  removed: "Passage removed",
  ambiguous: "Passage ambiguous",
};

export function PageCommentThread({
  row,
  orphaned,
  focused,
  canResolve,
  resolvedView = false,
  onFocus,
  onNavigate,
  onResolve,
  expanded = false,
  onToggle,
  canReply,
  draft,
  onDraft,
}: {
  row: Comment;
  /** Null when the passage still locates on the page. */
  orphaned: OrphanReason | null;
  focused: boolean;
  canResolve: boolean;
  resolvedView?: boolean;
  onFocus?: () => void;
  onNavigate?: () => void;
  onResolve: () => void;
  expanded?: boolean;
  onToggle: () => void;
  canReply: boolean;
  draft: string;
  onDraft: (value: string) => void;
}) {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  return (
    <div
      data-thread
      data-comment-id={row.id}
      data-orphaned={orphaned ?? undefined}
      className={
        "rounded-md border bg-surface p-2 " +
        (focused ? "border-strong" : "border-subtle") +
        (resolvedView ? " opacity-70" : "")
      }
    >
      {onNavigate ? <button type="button" onFocus={onFocus} onClick={onNavigate} disabled={orphaned !== null}
        aria-label={`Go to passage: ${row.anchor?.quote}`}
        title={orphaned ? "This passage was edited, removed, or is ambiguous." : "Go to this passage"}
        className="mb-1 flex w-full items-start gap-1 text-left text-[11px] italic text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-default">
        <span className="min-w-0 break-words">“{row.anchor?.quote}”</span>
      </button> : <p className="mb-1 break-words text-[11px] italic text-fg-muted">“{row.anchor?.quote}”</p>}
      {orphaned && (
        // RADD-1276: said in words, not an icon and a tooltip — a rail full
        // of these after a rewrite has to read as what it is.
        <p data-orphan-label className="mb-1 flex items-center gap-1 text-[11px] font-medium text-fg-secondary">
          <Unlink size={10} aria-hidden className="shrink-0" />
          {ORPHAN_LABEL[orphaned]}
        </p>
      )}
      <p className="flex items-baseline gap-1 text-[12px]">
        <span className="font-medium text-heading">{row.author?.name ?? "Unknown author"}</span>{" "}
        <span className="text-fg-faint" title={row.created_at}>
          {relativeTime(row.created_at)}
        </span>
        <CopyCommentLink href={commentHref(row.id)} className="ml-auto" />
      </p>
      <div className="mt-0.5">
        <RichViewer
          text={row.body}
          // RADD-1296: the author ticks their own checklist in place.
          onToggleTask={
            row.author && row.author.id === me?.id
              ? async (toggle) => {
                  await sendTaskToggle(apiCommentTasksPath(row.id), toggle, row.body);
                  await invalidateEntities(queryClient, Entity.comment);
                }
              : undefined
          }
        />
      </div>
      <button type="button" onClick={onToggle} aria-expanded={expanded}
        className="mt-2 text-xs text-fg-muted hover:text-fg hover:underline">
        {repliesLabel(row, expanded, canReply)}
      </button>
      {expanded && <CommentReplies row={row} canReply={canReply} draft={draft} onDraft={onDraft} canResolve={canResolve} linkFor={commentHref} />}
      {canResolve && (
        <button
          type="button"
          onClick={onResolve}
          className="mt-1 flex items-center gap-1 rounded px-1 text-[11px] text-fg-muted hover:text-fg cursor-pointer"
        >
          {resolvedView ? <RotateCcw size={10} aria-hidden /> : <Check size={10} aria-hidden />}
          {resolvedView ? "Unresolve" : "Resolve"}
        </button>
      )}
    </div>
  );
}
