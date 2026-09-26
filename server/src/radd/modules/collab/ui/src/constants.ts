import { API_BASE } from "@radd/plugin-sdk";

/** `POST /collab/pages/{id}/join` — a session for one page, as editor or observer. */
export const collabJoinPath = (pageId: string) => `/collab/pages/${pageId}/join`;

/** The room's socket — a SEPARATE socket from the realtime `/ws`: one room per page, the
 *  y-websocket protocol, `${COLLAB_WS_PATH}/{pageId}?session=…`. */
export const COLLAB_WS_PATH = `${API_BASE}/collab/pages`;

/** The elected saver writes the markdown this long after the last change. */
export const COLLAB_AUTOSAVE_MS = 1_500;

/** How many 4403/4409 closes a session answers with a fresh join before it hands the page back
 *  to its single-editor flow. */
export const COLLAB_REJOIN_LIMIT = 3;

/** What the editor's mode bar says while it is bound to the room. */
export const COLLAB_EDITOR_LABEL = "Editing together";
