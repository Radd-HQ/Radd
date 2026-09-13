import { useCallback, useEffect, useRef, useState } from "react";
import type { Me, Page } from "../../../lib/types";
import { CollabRole, type CollabRoleValue, type PresenceSnapshot } from "./model";
import { presenceColor } from "./presence-color";
import { usePresence } from "./presence";
import { isRejoinCode, openCollabRoom, type CollabRoom } from "./provider";
import { COLLAB_REJOIN_LIMIT } from "../../../lib/constants";
import { startSaver, type Saver } from "./saver";

/**
 * A page's room, as React state (spec 122).
 *
 * `role` is the intent: null = stay out (a visitor, or a surface with no room),
 * observer = presence only, editor = the live document. Changing it leaves
 * the current room and joins again — an observer who presses Edit becomes a
 * fresh editor session, which is what the server's seed grant is keyed on.
 * Editors also run the saver; the hook's `finish` sends the final write before
 * the caller leaves edit mode, so the cleanup's own final is skipped.
 *
 * `failed` is the fallback signal: the join was refused or the socket closed
 * with a 44xx. The page then runs the single-editor flow it always had.
 */
export interface CollabSession {
  room: CollabRoom | null;
  /** A join is in flight for the requested role. */
  joining: boolean;
  failed: boolean;
  presence: PresenceSnapshot;
  isSaver: boolean;
  /** The final save, if this client is the saver. Resolves when it is done. */
  finish: () => Promise<void>;
}

export interface CollabSessionOptions {
  pageId: string;
  role: CollabRoleValue | null;
  user: Me | null;
  /** The editor's live markdown (a ref read, never a captured value). */
  getMarkdown: () => string;
  onSaved?: (page: Page) => void;
  onSaveError?: (error: unknown) => void;
}

export function useCollabSession({
  pageId,
  role,
  user,
  getMarkdown,
  onSaved,
  onSaveError,
}: CollabSessionOptions): CollabSession {
  const [room, setRoom] = useState<CollabRoom | null>(null);
  const [failed, setFailed] = useState(false);
  const saverRef = useRef<Saver | null>(null);
  const finishedRef = useRef(false);
  // Latest callbacks without re-joining the room when a parent re-renders.
  const getMarkdownRef = useRef(getMarkdown);
  getMarkdownRef.current = getMarkdown;
  const onSavedRef = useRef(onSaved);
  onSavedRef.current = onSaved;
  const onSaveErrorRef = useRef(onSaveError);
  onSaveErrorRef.current = onSaveError;

  const userId = user?.id ?? null;
  const userName = user?.name ?? "";
  const avatarColor = user?.avatar_color ?? null;
  const avatarEmoji = user?.avatar_emoji ?? null;

  // A 4403/4409 close means "join again" (the room was reset under us, or it
  // expired); bumping this re-runs the effect with a fresh session. Bounded,
  // so a server that keeps refusing ends in the single-editor fallback.
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setRoom(null);
    setFailed(false);
    finishedRef.current = false;
    if (!role || !userId) return;
    let disposed = false;
    let opened: CollabRoom | null = null;
    const identity = { id: userId, avatar_color: avatarColor };
    openCollabRoom({
      pageId,
      role,
      user: { id: userId, name: userName, color: presenceColor(identity), emoji: avatarEmoji },
      onRefused: (code) => {
        if (disposed) return;
        setRoom(null);
        if (isRejoinCode(code) && attempt < COLLAB_REJOIN_LIMIT) {
          setAttempt((n) => n + 1);
          return;
        }
        setFailed(true);
      },
    }).then(
      (next) => {
        if (disposed) {
          next.close();
          return;
        }
        opened = next;
        if (role === CollabRole.editor) {
          saverRef.current = startSaver({
            pageId,
            session: next.session,
            doc: next.doc,
            awareness: next.awareness,
            getMarkdown: () => getMarkdownRef.current(),
            onSaved: (page) => onSavedRef.current?.(page),
            onError: (error) => onSaveErrorRef.current?.(error),
          });
        }
        setRoom(next);
      },
      () => {
        if (!disposed) setFailed(true);
      },
    );
    return () => {
      disposed = true;
      const saver = saverRef.current;
      saverRef.current = null;
      const current = opened;
      opened = null;
      if (!current) return;
      // The final write goes out before the departure frame, so the room
      // still counts this client as the saver while it is written.
      const stopping = saver ? saver.stop(!finishedRef.current) : Promise.resolve();
      void stopping.finally(() => current.close());
    };
  }, [pageId, role, userId, userName, avatarColor, avatarEmoji, attempt]);

  const presence = usePresence(room?.awareness ?? null, userId);
  const isSaver = room !== null && presence.saver === room.awareness.clientID;

  const finish = useCallback(async () => {
    const saver = saverRef.current;
    if (!saver) return;
    await saver.flush(true);
    finishedRef.current = true;
  }, []);

  return {
    room,
    joining: role !== null && userId !== null && room === null && !failed,
    failed,
    presence,
    isSaver,
    finish,
  };
}
