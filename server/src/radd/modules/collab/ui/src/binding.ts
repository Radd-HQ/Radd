import type { EditorBinding } from "@radd/plugin-sdk";
import { COLLAB_EDITOR_LABEL } from "./constants";
import type { CollabRoom } from "./room";

/**
 * The room as an editor binding (RADD-1397): what the page hands its editor. Keyed by the
 * session, so a rejoin binds a fresh editor. The binding code — y-prosemirror against the host's
 * shared ProseMirror — loads when an editor actually binds, not when someone reads the page.
 */
export function roomBinding(room: CollabRoom): EditorBinding {
  return {
    key: room.session,
    label: COLLAB_EDITOR_LABEL,
    bind: async (editor, signal) => {
      const { bindRoom } = await import("./bind-editor");
      return bindRoom(editor, room, signal);
    },
  };
}
