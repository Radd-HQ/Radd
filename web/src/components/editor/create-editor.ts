import {
  Editor,
  defaultValueCtx,
  editorViewOptionsCtx,
  rootCtx,
} from "@milkdown/kit/core";
import { commonmark } from "@milkdown/kit/preset/commonmark";
import { gfm } from "@milkdown/kit/preset/gfm";
import { clipboard } from "@milkdown/kit/plugin/clipboard";
import { history } from "@milkdown/kit/plugin/history";
import { indent, indentConfig } from "@milkdown/kit/plugin/indent";
import { listener, listenerCtx } from "@milkdown/kit/plugin/listener";
import { trailing } from "@milkdown/kit/plugin/trailing";
import { upload } from "@milkdown/kit/plugin/upload";

/**
 * The editor, composed from Milkdown directly (RADD-755).
 *
 * This is what `new Crepe(...)` was doing underneath: `Editor.make()` plus
 * commonmark, gfm, and six small plugins — listener, history, indent, trailing,
 * clipboard, upload. Everything else Crepe added was CHROME, and by the time
 * this landed the epic had replaced all of it, so the constructor was wrapping
 * a list we could write ourselves in a dozen lines.
 *
 * Keeping the list here rather than inline in two components is the point: the
 * editor and the read-only viewer must be the same engine, or "read and edit
 * look identical" becomes a coincidence that holds until someone adds a plugin
 * to one of them.
 */
export interface EditorOptions {
  root: HTMLElement;
  /** Initial markdown. The editor is uncontrolled after creation. */
  value: string;
  /** False for the viewer — same engine, no editing. A function is asked per
   *  transaction: the collaborative editor (spec 122) answers false until the
   *  room's document has arrived, so nothing typed into the local copy is
   *  silently replaced by the shared one. */
  editable: boolean | (() => boolean);
  /** Fires on every edit with the current markdown. Omitted for the viewer. */
  onMarkdown?: (markdown: string) => void;
  /** Off in collaborative mode (spec 122): the Yjs undo manager takes over so
   *  Mod-z undoes YOUR edits, not a colleague's. Default on. */
  history?: boolean;
}

export function makeEditor({
  root,
  value,
  editable,
  onMarkdown,
  history: withHistory = true,
}: EditorOptions): Editor {
  const isEditable = typeof editable === "function" ? editable : () => editable;
  const editor = Editor.make()
    .config((ctx) => {
      ctx.set(rootCtx, root);
      ctx.set(defaultValueCtx, value);
      // A FUNCTION, not a boolean: ProseMirror asks per transaction, so a
      // viewer that later becomes editable needs no rebuild.
      ctx.set(editorViewOptionsCtx, { editable: isEditable });
      // Four spaces, matching what the editor used to indent with — a change
      // here would rewrite the leading whitespace of every nested list on save.
      ctx.update(indentConfig.key, (base) => ({ ...base, size: 4 }));
    })
    .config((ctx) => {
      if (onMarkdown) ctx.get(listenerCtx).markdownUpdated((_ctx, markdown) => onMarkdown(markdown));
    })
    .use(commonmark)
    .use(gfm)
    .use(listener);
  if (withHistory) editor.use(history);
  return (
    editor
      .use(indent)
      .use(trailing)
      .use(clipboard)
      // Registered unconditionally so the paste/drop path exists; the surfaces
      // that can upload supply the uploader through `uploadConfig`, and the ones
      // that cannot leave it at the default, which drops the file.
      .use(upload)
  );
}
