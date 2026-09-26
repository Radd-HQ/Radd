import type { LiveDocumentHandle, LiveDocumentOpen, LiveDocumentState } from "@radd/plugin-sdk";
import { roomBinding } from "./binding";
import { COLLAB_REJOIN_LIMIT } from "./constants";
import { EditingNow, SavingStatus } from "./EditingNow";
import { CollabRole } from "./model";
import { createPresenceStore } from "./presence";
import { presenceColor } from "./presence-color";
import type { CollabRoom } from "./room";
import { startSaver, type Saver } from "./saver";

/**
 * A page's live session: editing → editor on the shared doc, reading → observer; editing without
 * write access has no session. A new request is a new session (the server's seed grant is keyed on
 * it). `unavailable` = join refused or a 44xx close → the page's single-editor flow; 4403/4409
 * rejoin first, bounded. `finish` writes the final save so `close` skips it.
 */
export function openPageSession(
  request: LiveDocumentOpen,
  update: (state: LiveDocumentState) => void,
): LiveDocumentHandle {
  const role = request.editing ? CollabRole.editor : CollabRole.observer;
  const { viewer } = request;
  const user = { id: viewer.id, name: viewer.name, color: presenceColor(viewer), emoji: viewer.avatar_emoji ?? null };
  const presence = createPresenceStore(viewer.id);
  const chrome = {
    presence: <EditingNow store={presence} />,
    saving: role === CollabRole.editor ? <SavingStatus store={presence} /> : null,
  };
  let closed = false;
  let finished = false;
  let attempt = 0;
  let room: CollabRoom | null = null;
  let saver: Saver | null = null;

  const push = (status: LiveDocumentState["status"], current: CollabRoom | null = null) => {
    if (closed) return;
    update({
      status,
      role,
      binding: current && role === CollabRole.editor ? roomBinding(current) : null,
      ...chrome,
    });
  };

  /** Out of the room: the final write goes out before the departure frame, so the room still
   *  counts this client as the saver while it is written. */
  const leave = (final: boolean) => {
    const current = room;
    const stopping = saver ? saver.stop(final) : Promise.resolve();
    room = null;
    saver = null;
    presence.detach();
    if (current) void stopping.finally(() => current.close());
  };

  const join = () => {
    const mine = ++attempt;
    push("joining");
    // The transport (yjs + y-websocket) loads with a page's first session, not with this remote.
    void import("./room")
      .then(({ isRejoinCode, openCollabRoom }) =>
        openCollabRoom({
          pageId: request.entityId,
          role,
          user,
          onRefused: (code) => {
            if (closed || mine !== attempt) return;
            leave(!finished);
            if (isRejoinCode(code) && attempt <= COLLAB_REJOIN_LIMIT) join();
            else push("unavailable");
          },
        }),
      )
      .then(
        (opened) => {
          if (closed || mine !== attempt) {
            opened.close();
            return;
          }
          room = opened;
          presence.attach(opened.awareness);
          if (role === CollabRole.editor) {
            saver = startSaver({
              session: opened.session,
              doc: opened.doc,
              awareness: opened.awareness,
              getMarkdown: request.getMarkdown,
              save: request.save,
            });
          }
          push("live", opened);
        },
        () => {
          if (mine === attempt) push("unavailable");
        },
      );
  };

  if (request.editing && !request.canWrite) {
    update({ status: "unavailable", role: null, binding: null });
    closed = true;
  } else {
    join();
  }
  return {
    finish: async () => {
      if (!saver) return;
      await saver.flush(true);
      finished = true;
    },
    close: () => {
      if (closed) return;
      closed = true;
      leave(!finished);
    },
  };
}
