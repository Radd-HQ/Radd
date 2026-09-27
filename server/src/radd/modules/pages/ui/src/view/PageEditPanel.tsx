import { Button, Callout, LiveStatus, RichEditor, type EditorTransform, type InlineAnchorRef, type LiveDocument, CalloutKind } from "@radd/plugin-sdk";
import type { PageUpdate } from "../types";

const EDITOR_CLASS = "[&_.ProseMirror]:min-h-[24rem]";
const PLACEHOLDER =
  "Write the page… use the toolbar for headings, tables, code — or type markdown.";

/** Edit mode: a live session's shared editor with Done, or (no session) Save with `expected_version` and
 *  reload-or-overwrite on a 409 — see `usePageEditing`. A session that appears while the page's own
 *  editor is open is offered ("Join and merge"), never swapped in over the draft (RADD-1461). */
export function PageEditPanel({
  draft,
  onDraft,
  pendingTransform,
  attachTo,
  live,
  legacy,
  liveOffered,
  onJoinLive,
  editVersion,
  conflict,
  saving,
  onSave,
  onReload,
  onCancel,
  finishing,
  onDone,
  inlineAnchors,
  onDetachedComments,
}: {
  draft: string;
  onDraft: (markdown: string) => void;
  pendingTransform: EditorTransform | null;
  /** Where pasted and inserted images are stored (spec 102). */
  attachTo: { entityType: string; entityId: string };
  live: LiveDocument;
  /** Run the single-editor flow (no live session: none offered, refused, or a visitor). */
  legacy: boolean;
  /** A live session became available while the page's own editor is open. */
  liveOffered: boolean;
  /** Join it, taking the draft along. */
  onJoinLive: () => void;
  editVersion: number;
  conflict: boolean;
  saving: boolean;
  onSave: (body: PageUpdate) => void;
  onReload: () => void;
  onCancel: () => void;
  finishing: boolean;
  onDone: () => void;
  /** RADD-1274: the page's open inline comments, for a transform review's count. */
  inlineAnchors: InlineAnchorRef[];
  onDetachedComments: (ids: string[]) => void;
}) {
  const binding = live.status === LiveStatus.live ? live.binding : null;
  const editorProps = {
    value: draft, onChange: onDraft, extensions: true, attachTo, autoFocus: true, placeholder: PLACEHOLDER,
    initialTransform: pendingTransform ?? undefined, inlineAnchors, onDetachedComments, className: EDITOR_CLASS,
  };

  if (!legacy) {
    return (
      <div aria-label="Edit page content" className="mt-3 flex flex-col gap-2">
        {binding ? (
          <RichEditor key={binding.key} {...editorProps} binding={binding} />
        ) : (
          <div className="min-h-24 animate-pulse rounded-md border border-strong bg-surface px-3 py-2 text-[13px] text-fg-faint">
            Joining the page…
          </div>
        )}
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={onDone} disabled={finishing || !binding}>
            {finishing ? "Saving…" : "Done"}
          </Button>
          {binding && live.saving}
        </div>
      </div>
    );
  }

  return (
    <div aria-label="Edit page content" className="mt-3 flex flex-col gap-2">
      {liveOffered && (
        <Callout kind="info">
          <div className="flex items-center gap-2">
            <span>
              This page can now be edited together. Your draft stays yours until you join; joining
              brings it into the shared page as your change.
            </span>
            <Button size="sm" className="ml-auto shrink-0" onClick={onJoinLive}>Join and merge</Button>
          </div>
        </Callout>
      )}
      {conflict && (
        <Callout kind={CalloutKind.warning}>
          <div className="flex items-center gap-2">
            This page changed since you opened it — reload it (discarding your draft) or
            overwrite.
            <span className="ml-auto flex shrink-0 gap-2">
              <button
                type="button"
                onClick={onReload}
                className="rounded border border-callout-warning-border/60 px-1.5 py-0.5 hover:bg-callout-warning-border/10 cursor-pointer"
              >
                Reload
              </button>
              <button
                type="button"
                onClick={() => onSave({ body: draft })}
                className="rounded border border-callout-warning-border/60 px-1.5 py-0.5 hover:bg-callout-warning-border/10 cursor-pointer"
              >
                Overwrite
              </button>
            </span>
          </div>
        </Callout>
      )}
      <RichEditor {...editorProps} />
      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={() => onSave({ body: draft, expected_version: editVersion })}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
