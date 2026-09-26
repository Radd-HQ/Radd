import { Button, Callout, LiveStatus, RichEditor, type EditorTransform, type InlineAnchorRef, type LiveDocument } from "@radd/plugin-sdk";
import type { PageUpdate } from "../types";

const EDITOR_CLASS = "[&_.ProseMirror]:min-h-[24rem]";
const PLACEHOLDER =
  "Write the page… use the toolbar for headings, tables, code — or type markdown.";

/**
 * The page's edit mode (spec 122): two flows behind one panel.
 *
 * In a LIVE SESSION the document is shared, so there is nothing to Save or
 * Cancel — every keystroke is already everyone's; the button is **Done**, which
 * leaves the session (its last save goes out first), and the session's own
 * chrome says who saves. The session and the binding that shares the editor's
 * document are a plugin's (RADD-1397). Without one the spec-43 single-editor
 * flow runs exactly as before: Save with `expected_version`, and the
 * reload-or-overwrite dialog on a 409.
 */
export function PageEditPanel({
  draft,
  onDraft,
  pendingTransform,
  attachTo,
  live,
  legacy,
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

  if (!legacy) {
    return (
      <div aria-label="Edit page content" className="mt-3 flex flex-col gap-2">
        {binding ? (
          <RichEditor
            key={binding.key}
            value={draft}
            onChange={onDraft}
            extensions
            attachTo={attachTo}
            autoFocus
            placeholder={PLACEHOLDER}
            initialTransform={pendingTransform ?? undefined}
            inlineAnchors={inlineAnchors}
            onDetachedComments={onDetachedComments}
            binding={binding}
            className={EDITOR_CLASS}
          />
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
      {conflict && (
        <Callout kind="warning">
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
      <RichEditor
        value={draft}
        onChange={onDraft}
        extensions
        attachTo={attachTo}
        autoFocus
        placeholder={PLACEHOLDER}
        initialTransform={pendingTransform ?? undefined}
        inlineAnchors={inlineAnchors}
        onDetachedComments={onDetachedComments}
        className={EDITOR_CLASS}
      />
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
