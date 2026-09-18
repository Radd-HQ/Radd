import { Check, RotateCcw, Unlink } from "lucide-react";
import { relativeTime } from "../../lib/dates";
import type { Comment } from "../../lib/types";
import { LazyRichViewer as RichViewer } from "../editor/LazyRichViewer";
import { CommentReplies, repliesLabel } from "../comments/CommentReplies";

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
  orphaned: boolean;
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
  return (
    <div
      data-thread
      data-comment-id={row.id}
      data-orphaned={orphaned || undefined}
      className={
        "rounded-md border bg-surface p-2 " +
        (focused ? "border-strong" : "border-subtle") +
        (resolvedView ? " opacity-70" : "")
      }
    >
      {onNavigate ? <button type="button" onFocus={onFocus} onClick={onNavigate} disabled={orphaned}
        aria-label={`Go to passage: ${row.anchor?.quote}`}
        title={orphaned ? "This passage was edited, removed, or is ambiguous." : "Go to this passage"}
        className="mb-1 flex w-full items-start gap-1 text-left text-[11px] italic text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-default">
        {orphaned && <Unlink size={10} aria-hidden className="shrink-0" />}
        <span className="min-w-0 break-words">“{row.anchor?.quote}”</span>
      </button> : <p className="mb-1 break-words text-[11px] italic text-fg-muted">“{row.anchor?.quote}”</p>}
      <p className="text-[12px]">
        <span className="font-medium text-heading">{row.author?.name ?? "Unknown author"}</span>{" "}
        <span className="text-fg-faint" title={row.created_at}>
          {relativeTime(row.created_at)}
        </span>
      </p>
      <div className="mt-0.5">
        <RichViewer text={row.body} />
      </div>
      <button type="button" onClick={onToggle} aria-expanded={expanded}
        className="mt-2 text-xs text-fg-muted hover:text-fg hover:underline">
        {repliesLabel(row, expanded, canReply)}
      </button>
      {expanded && <CommentReplies row={row} canReply={canReply} draft={draft} onDraft={onDraft} />}
      {canResolve && (
        <button
          type="button"
          onClick={onResolve}
          className="mt-1 flex items-center gap-1 rounded px-1 text-[11px] text-fg-muted hover:text-fg cursor-pointer"
        >
          {resolvedView ? <RotateCcw size={10} aria-hidden /> : <Check size={10} aria-hidden />}
          {resolvedView ? "Reopen" : "Resolve"}
        </button>
      )}
    </div>
  );
}
