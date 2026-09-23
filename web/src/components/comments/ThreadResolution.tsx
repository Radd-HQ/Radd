import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, MessagesSquare, RotateCcw } from "lucide-react";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { apiCommentPath } from "../../lib/constants";
import { relativeTime } from "../../lib/dates";
import type { Comment } from "../../lib/types";
import { Button } from "../Button";

/**
 * A thread's status chip, for the comment header: what makes a resolvable
 * thread read as one rather than as an ordinary comment with replies.
 */
export function ThreadBadge({ comment }: { comment: Comment }) {
  if (!comment.is_thread) return null;
  const resolved = !!comment.resolved_at;
  const who = comment.resolver_name ? ` by ${comment.resolver_name}` : "";
  return (
    <span
      data-thread-state={resolved ? "resolved" : "unresolved"}
      title={resolved && comment.resolved_at ? `Resolved${who} ${relativeTime(comment.resolved_at)}` : undefined}
      className={
        "inline-flex items-center gap-1 rounded border px-1.5 py-px text-[10px] font-medium " +
        (resolved
          ? "border-callout-success-border bg-callout-success-fill text-callout-success-ink"
          : "border-callout-info-border bg-callout-info-fill text-callout-info-ink")
      }
    >
      {resolved ? <Check size={10} aria-hidden /> : <MessagesSquare size={10} aria-hidden />}
      {resolved ? `Resolved${who}` : "Unresolved thread"}
    </span>
  );
}

/** Resolve / Reopen, on the root: lifecycle belongs to the thread, never a reply. */
export function ResolveThreadButton({ comment }: { comment: Comment }) {
  const client = useQueryClient();
  const change = useMutation({
    mutationFn: () => api.post<Comment>(`${apiCommentPath(comment.id)}/${comment.resolved_at ? "reopen" : "resolve"}`, {}),
    onSuccess: () => invalidateEntities(client, Entity.comment),
  });
  if (!comment.is_thread) return null;
  const resolved = !!comment.resolved_at;
  return (
    <>
      <Button size="sm" variant="secondary" disabled={change.isPending} onClick={() => change.mutate()}
        data-thread-resolution={comment.id}>
        {resolved ? <RotateCcw size={12} aria-hidden /> : <Check size={12} aria-hidden />}
        {resolved ? "Unresolve thread" : "Resolve thread"}
      </Button>
      {change.isError && <span role="alert" className="text-xs text-status-danger-ink">{errorMessage(change.error)}</span>}
    </>
  );
}

/** All comments ⇄ Unresolved threads, above a discussion (issues and pages alike). */
export function ThreadFilter({ unresolvedOnly, onChange }: { unresolvedOnly: boolean; onChange: (value: boolean) => void }) {
  return (
    <div role="radiogroup" aria-label="Show" className="flex gap-1 self-start rounded-md border border-subtle p-0.5">
      {([[false, "All comments"], [true, "Unresolved threads"]] as const).map(([value, label]) => (
        <button key={label} type="button" role="radio" aria-checked={unresolvedOnly === value}
          onClick={() => onChange(value)} data-comment-filter={value ? "unresolved" : "all"}
          className={"rounded px-2 py-0.5 text-[11px] font-medium cursor-pointer transition-colors " +
            "focus-visible:outline-2 focus-visible:outline-focus " +
            (unresolvedOnly === value ? "bg-overlay text-heading" : "text-fg-muted hover:text-fg")}>
          {label}
        </button>
      ))}
    </div>
  );
}

/** The left rule that marks a thread card: accent while open, green once resolved. */
export function threadRuleClass(comment: Comment): string {
  if (!comment.is_thread) return "";
  return " border-l-2 " + (comment.resolved_at ? "border-l-status-success" : "border-l-accent");
}
