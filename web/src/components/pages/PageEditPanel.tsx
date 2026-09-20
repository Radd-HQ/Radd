import { LazyRichEditor as RichEditor } from "../editor/LazyRichEditor";
import type { AiRun } from "../editor/ai";
import type { CollabSession } from "../editor/collab/useCollabSession";
import type { InlineAnchorRef } from "../editor/detached-comments";
import { Button } from "../Button";
import { Callout } from "../Callout";
import type { PageUpdate } from "../../lib/types";

const EDITOR_CLASS = "[&_.ProseMirror]:min-h-[24rem]";
const PLACEHOLDER =
  "Write the page… use the toolbar for headings, tables, code — or type markdown.";

/**
 * The page's edit mode (spec 122): two flows behind one panel.
 *
 * In a ROOM the document is shared, so there is nothing to Save or Cancel —
 * every keystroke is already everyone's; the button is **Done**, which leaves
 * the room (the elected saver's final write goes out first). When the room
 * cannot be joined the spec-43 single-editor flow runs exactly as before:
 * Save with `expected_version`, and the reload-or-overwrite dialog on a 409.
 */
export function PageEditPanel({
  draft,
  onDraft,
  pendingAiRun,
  onUploadImage,
  collab,
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
  pendingAiRun: AiRun | null;
  onUploadImage: (file: File) => Promise<string>;
  collab: CollabSession;
  /** Run the single-editor flow (the room refused us, or there is no account). */
  legacy: boolean;
  editVersion: number;
  conflict: boolean;
  saving: boolean;
  onSave: (body: PageUpdate) => void;
  onReload: () => void;
  onCancel: () => void;
  finishing: boolean;
  onDone: () => void;
  /** RADD-1274: the page's open inline comments, for the AI review's count. */
  inlineAnchors: InlineAnchorRef[];
  onDetachedComments: (ids: string[]) => void;
}) {
  const room = collab.room;
  const saverName = collab.presence.people.find((person) =>
    person.clientIds.includes(collab.presence.saver ?? -1),
  )?.user.name;

  if (!legacy) {
    return (
      <div aria-label="Edit page content" className="mt-3 flex flex-col gap-2">
        {room ? (
          <RichEditor
            key={room.session}
            value={draft}
            onChange={onDraft}
            extensions
            onUploadImage={onUploadImage}
            autoFocus
            placeholder={PLACEHOLDER}
            initialAiRun={pendingAiRun ?? undefined}
            inlineAnchors={inlineAnchors}
            onDetachedComments={onDetachedComments}
            collab={{
              doc: room.doc,
              provider: room.provider,
              awareness: room.awareness,
              seed: room.seed,
              template: draft,
            }}
            className={EDITOR_CLASS}
          />
        ) : (
          <div className="min-h-24 animate-pulse rounded-md border border-strong bg-surface px-3 py-2 text-[13px] text-fg-faint">
            Joining the page…
          </div>
        )}
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={onDone} disabled={finishing || !room}>
            {finishing ? "Saving…" : "Done"}
          </Button>
          {room && (
            <span className="text-[11px] text-fg-muted" data-collab-saver={collab.isSaver}>
              {collab.isSaver
                ? "Saving as you type"
                : saverName
                  ? `Saved by ${saverName}`
                  : "Saving as you type"}
            </span>
          )}
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
        onUploadImage={onUploadImage}
        autoFocus
        placeholder={PLACEHOLDER}
        initialAiRun={pendingAiRun ?? undefined}
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
