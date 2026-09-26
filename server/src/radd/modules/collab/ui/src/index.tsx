import { definePlugin, type LiveDocumentSource } from "@radd/plugin-sdk";
import { openPageSession } from "./session";

/**
 * Co-editing's UI (spec 122, RADD-1397): the collab plugin answers the pages' "is a live session
 * available?" with a room — presence for readers, a shared document for editors, the elected
 * saver, and the chrome that says who is here and who saves. The host knows none of it: its editor
 * takes a binding, the page takes the answer, and with this plugin disabled neither loads a line
 * of it.
 *
 * The entry is small on purpose: the transport (yjs, y-websocket) loads with a page's first
 * session, and the editor binding (y-prosemirror over the host's shared ProseMirror) with the
 * first edit.
 */
const pages: LiveDocumentSource = { id: "collab.pages", entityType: "page", open: openPageSession };

export default definePlugin({ liveDocuments: [pages] });
