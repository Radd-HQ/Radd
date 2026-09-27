import { Check, RotateCcw, Unlink } from "lucide-react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  Button, CommentReplies, CopyCommentLink, RichViewer, commentHref, invalidateEntities, relativeTime, sendTaskToggle,
  useCurrentUser, type CommentRow, type TaskToggle, type ThreadExpansion, Entity } from "@radd/plugin-sdk";
import { commentTasksPath } from "../endpoints";

/** Why a comment no longer points at the page (RADD-1276): its passage was
 *  edited away, or now appears more than once and the context cannot choose. */
export type OrphanReason = "removed" | "ambiguous";

const ORPHAN_LABEL: Record<OrphanReason, string> = {
  removed: "Passage removed",
  ambiguous: "Passage ambiguous",
};

/** RADD-1296: the author ticks their own checklist in place; nobody else can. */
export function ownTaskToggle(row: CommentRow, meId: string | undefined, queryClient: QueryClient) {
  if (!row.author || row.author.id !== meId) return undefined;
  return async (toggle: TaskToggle) => {
    await sendTaskToggle(commentTasksPath(row.id), toggle, row.body);
    await invalidateEntities(queryClient, Entity.comment);
  };
}

/**
 * One inline comment: its quote, the comment, and (RADD-1448) the same thread footer as every other
 * comment — its replies unless resolved, a Reply action, and Resolve. A `preview` (the hover card)
 * shows the comment and how many replies it has, and fetches nothing; opening it shows the thread.
 */
export function PageCommentThread({
  row,
  orphaned,
  focused,
  canResolve,
  resolvedView = false,
  onFocus,
  onNavigate,
  onResolve,
  preview = false,
  expansion,
  canReply,
  draft,
  onDraft,
}: {
  row: CommentRow;
  /** Null when the passage still locates on the page. */
  orphaned: OrphanReason | null;
  focused: boolean;
  canResolve: boolean;
  resolvedView?: boolean;
  onFocus?: () => void;
  onNavigate?: () => void;
  onResolve: () => void;
  preview?: boolean;
  /** Whose replies show; required unless `preview`. */
  expansion?: ThreadExpansion;
  canReply: boolean;
  draft: string;
  onDraft: (value: string) => void;
}) {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  const replyCount = row.reply_count ?? 0;
  return (
    <div
      data-thread
      data-comment-id={row.id}
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
        <RichViewer text={row.body} onToggleTask={ownTaskToggle(row, me?.id, queryClient)} />
      </div>
      {preview ? (
        replyCount > 0 && (
          <p className="mt-1 text-[11px] text-fg-muted" data-reply-count>
            {replyCount} {replyCount === 1 ? "reply" : "replies"}
          </p>
        )
      ) : (
        <CommentReplies
          row={row}
          expansion={expansion}
          canReply={canReply}
          draft={draft}
          onDraft={onDraft}
          canResolve={canResolve}
          linkFor={commentHref}
          actions={
            canResolve && (
              <Button variant="ghost" onClick={onResolve} data-thread-resolution={row.id}>
                {resolvedView ? <RotateCcw size={12} aria-hidden /> : <Check size={12} aria-hidden />}
                {resolvedView ? "Unresolve" : "Resolve"}
              </Button>
            )
          }
        />
      )}
    </div>
  );
}
