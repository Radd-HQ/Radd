import { definePlugin, type LiveDocumentSource } from "@radd/plugin-sdk";
import { openPageSession } from "./session";

/** Co-editing (spec 122): answers a page's live-session request with a room. The entry stays small —
 *  yjs/y-websocket load with the first session, the editor binding with the first edit. */
const pages: LiveDocumentSource = { id: "collab.pages", entityType: "page", open: openPageSession };

export default definePlugin({ liveDocuments: [pages] });
