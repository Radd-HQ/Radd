import { Plugin } from "prosemirror-state";
import { prosemirrorToYDoc, redo, undo, yCursorPlugin, ySyncPlugin, yUndoPlugin } from "y-prosemirror";
import { applyUpdate, encodeStateAsUpdate } from "yjs";
import type { BindableEditor } from "@radd/plugin-sdk";
import { cursorBuilder, selectionBuilder } from "./cursors";
import { COLLAB_FRAGMENT, whenDocumentReady, type CollabRoom } from "./room";

/**
 * Bind the host's editor to the room's document (spec 122, RADD-1397).
 *
 * This chunk loads when an editor binds, and runs AGAINST THE HOST'S
 * ProseMirror: `prosemirror-state`/`-view`/`-model` — here and inside
 * y-prosemirror — resolve through the import map to the instances the host's
 * editor runs, so the sync plugin's key, its `instanceof` checks and the nodes
 * it builds are the editor's own. yjs is this remote's alone: nothing outside
 * it ever touches a Y.Doc.
 *
 * The seed rule: wait for the room, and only the client the join elected
 * seeds — and only into a fragment that is STILL empty after sync, or two
 * first joiners would double the page.
 */
export async function bindRoom(editor: BindableEditor, room: CollabRoom, signal: AbortSignal): Promise<() => void> {
  await whenDocumentReady(room, signal);
  if (signal.aborted) return () => {};
  const fragment = room.doc.getXmlFragment(COLLAB_FRAGMENT);
  if (room.seed && fragment.length === 0) {
    const template = prosemirrorToYDoc(editor.parse(editor.markdown), COLLAB_FRAGMENT);
    applyUpdate(room.doc, encodeStateAsUpdate(template));
    template.destroy();
  }
  return editor.addPlugins([
    ySyncPlugin(fragment),
    // The Yjs undo manager replaces the editor's history: Mod-z undoes YOUR
    // edits to the shared document, not a colleague's.
    yUndoPlugin(),
    undoKeys(),
    yCursorPlugin(room.awareness, { cursorBuilder, selectionBuilder }),
  ]);
}

const MAC = typeof navigator !== "undefined" && /Mac|iP(hone|[oa]d)/.test(navigator.platform);

/** Mod-z undoes, Mod-y and Mod-Shift-z redo — through the room's undo manager. */
function undoKeys(): Plugin {
  return new Plugin({
    props: {
      handleKeyDown: (view, event) => {
        const mod = MAC ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey;
        if (!mod || event.altKey) return false;
        const key = event.key.toLowerCase();
        if (key === "z") return event.shiftKey ? redo(view.state) : undo(view.state);
        if (key === "y" && !event.shiftKey) return redo(view.state);
        return false;
      },
    },
  });
}
