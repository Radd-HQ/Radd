import { useMutation } from "@tanstack/react-query";
import type { EditorTransform } from "@radd/plugin-sdk";
import { api, errorMessage } from "../../lib/api";
import { apiCommentPath } from "../../lib/constants/api-paths";
import type { Comment } from "../../lib/types";
import { Button } from "../Button";
import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import type { QuickAction } from "../items/quick-actions";
import { escapeBelongsInside } from "./escape";

/**
 * The inline editor a comment and a reply share (spec 37; RADD-1477 gave replies the same one):
 * `PATCH /comments/{id}` with the body; Cmd+Enter or Save submits once. The draft is the CALLER's
 * (`draft`/`onDraft`), so Cancel and Escape close the editor and keep what was typed — reopening
 * shows it — and a save that lands clears it through `onSaved`.
 */
export function CommentEditForm({
  comment,
  draft,
  onDraft,
  onSaved,
  onCancel,
  quickActions,
  onUploadImage,
  initialTransform,
}: {
  comment: Comment;
  draft: string;
  onDraft: (value: string) => void;
  /** The PATCH landed: the caller refreshes its list and drops the draft. */
  onSaved: () => void;
  onCancel: () => void;
  quickActions?: QuickAction[];
  onUploadImage?: (file: File) => Promise<string>;
  /** From a read action: run this transform as soon as the editor mounts. */
  initialTransform?: EditorTransform;
}) {
  const save = useMutation({
    mutationFn: () => api.patch<Comment>(apiCommentPath(comment.id), { body: draft }),
    onSuccess: () => onSaved(),
  });
  const submit = () => {
    if (!draft.trim() || draft === comment.body) onCancel();
    else if (!save.isPending) save.mutate();
  };
  return (
    <div
      className="mt-1 flex flex-col gap-1.5"
      data-comment-edit={comment.id}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || escapeBelongsInside(event)) return;
        event.preventDefault();
        event.stopPropagation(); // the editor, not the peek or popover around it
        onCancel();
      }}
    >
      <RichEditor
        value={draft}
        onChange={onDraft}
        onUploadImage={onUploadImage}
        autoFocus
        onSubmitShortcut={submit}
        quickActions={quickActions}
        initialTransform={initialTransform}
      />
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={submit} disabled={save.isPending} data-comment-edit-save>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} data-comment-edit-cancel>
          Cancel
        </Button>
        {save.isError && (
          <span role="alert" className="text-xs text-status-danger-ink">{errorMessage(save.error)}</span>
        )}
      </div>
    </div>
  );
}
