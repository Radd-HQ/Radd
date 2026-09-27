import type { EditorBinding } from "@radd/plugin-sdk";
import { COLLAB_EDITOR_LABEL } from "./constants";
import type { CollabRoom } from "./room";

export interface RoomBindingOptions {
  /** The editor opened with unsaved changes the session must keep (`LiveDocumentRequest.keepDraft`). */
  keepDraft: boolean;
  /** The bind failed (its chunk did not load, the room went away mid-bind, the binding threw): the
   *  session hands the page back to its own editor rather than leave a read-only one behind Done. */
  onFailed: (error: unknown) => void;
}

/**
 * The room as an editor binding (RADD-1397): what the page hands its editor. Keyed by the
 * session, so a rejoin binds a fresh editor. The binding code — y-prosemirror against the host's
 * shared ProseMirror — loads when an editor actually binds, not when someone reads the page.
 */
export function roomBinding(room: CollabRoom, { keepDraft, onFailed }: RoomBindingOptions): EditorBinding {
  return {
    key: room.session,
    label: COLLAB_EDITOR_LABEL,
    bind: async (editor, signal) => {
      try {
        const { bindRoom } = await import("./bind-editor");
        return await bindRoom(editor, room, signal, { keepDraft });
      } catch (error) {
        // An editor that went first is not a failure; anything else is the session's to report.
        if (!signal.aborted) onFailed(error);
        throw error;
      }
    },
  };
}
