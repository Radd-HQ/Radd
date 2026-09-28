import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";
import { Entity, IconButton, invalidateEntities, useConfirm } from "@radd/plugin-sdk";
import { api, errorMessage } from "../../lib/api";
import { apiCommentPath } from "../../lib/constants/api-paths";
import type { Comment } from "../../lib/types";

/**
 * Edit and Delete on a reply (RADD-1477, GitHub #34), for its author or a manager — the comment's
 * own pair, in the reply's header, shown on hover and while one has focus. Delete asks first; a
 * reply has no replies of its own, so nothing else goes with it. Every surface showing the thread
 * refreshes through the comment entity, so the count and the thread's state follow.
 */
export function ReplyActions({ reply, onEdit }: { reply: Comment; onEdit: () => void }) {
  const client = useQueryClient();
  const [confirmDialog, confirm] = useConfirm();
  const remove = useMutation({
    mutationFn: () => api.delete<void>(apiCommentPath(reply.id)),
    onSettled: () => void invalidateEntities(client, Entity.comment),
  });
  const askToDelete = async () => {
    const ok = await confirm({
      title: "Delete reply",
      message: "Delete this reply? This cannot be undone.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) remove.mutate();
  };
  return (
    <span
      className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover/reply:opacity-100 focus-within:opacity-100"
      data-reply-actions={reply.id}
    >
      <IconButton onClick={onEdit} aria-label="Edit reply" title="Edit reply">
        <Pencil size={11} aria-hidden />
      </IconButton>
      <IconButton danger onClick={() => void askToDelete()} disabled={remove.isPending}
        aria-label="Delete reply" title="Delete reply">
        <Trash2 size={11} aria-hidden />
      </IconButton>
      {remove.isError && (
        <span role="alert" className="text-[11px] text-status-danger-ink">{errorMessage(remove.error)}</span>
      )}
      {confirmDialog}
    </span>
  );
}
