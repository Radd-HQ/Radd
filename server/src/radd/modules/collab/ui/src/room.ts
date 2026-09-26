import { Doc } from "yjs";
import type { Awareness } from "y-protocols/awareness";
import { WebsocketProvider } from "y-websocket";
import { api } from "@radd/plugin-sdk";
import { COLLAB_WS_PATH, collabJoinPath } from "./constants";
import type { CollabRoleValue, CollabUser } from "./model";

/**
 * The room, from the client's side (spec 122): one HTTP join that mints a
 * session, then a y-websocket provider on a socket of its own — NOT the
 * spec-27 `/ws`, which carries invalidations one way and knows nothing about
 * documents. `disableBc` because every tab is its own session: BroadcastChannel
 * would let two tabs share a document the server thinks only one of them
 * joined.
 *
 * This module is the remote's transport chunk: yjs and y-websocket load with a
 * page's first session, never with the remote's entry (RADD-1397).
 */

/** `POST /collab/pages/{id}/join`. */
export interface CollabJoin {
  session: string;
  role: CollabRoleValue;
  /** This client may initialise an empty document from the markdown. */
  seed: boolean;
  page_version: number;
}

/** Server close codes on the room socket. y-websocket treats the whole
 *  4400–4499 band as terminal (no reconnect) and emits `closed`. */
const CollabCloseCode = {
  notSignedIn: 4401,
  /** Session unknown, not yours, or the room is gone — join again. */
  unknownSession: 4403,
  /** The body was written by something outside the room and the room was
   *  reset — join again and sync the replaced document. */
  documentReplaced: 4409,
} as const;

/** A refusal the client answers by joining again rather than giving up. */
export function isRejoinCode(code: number): boolean {
  return code === CollabCloseCode.unknownSession || code === CollabCloseCode.documentReplaced;
}

/** The Y.XmlFragment the ProseMirror document binds to — the binding, the
 *  readiness check, AND the seed: `prosemirrorToYDoc` names its fragment by
 *  the same argument, so a different name here would seed a fragment nobody
 *  is bound to. */
export const COLLAB_FRAGMENT = "prosemirror";

export interface CollabRoom {
  pageId: string;
  session: string;
  role: CollabRoleValue;
  seed: boolean;
  pageVersion: number;
  doc: Doc;
  provider: WebsocketProvider;
  awareness: Awareness;
  /** Announce the departure, then tear everything down. Idempotent. */
  close: () => void;
}

function collabWsBase(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${COLLAB_WS_PATH}`;
}

interface OpenRoomOptions {
  pageId: string;
  role: CollabRoleValue;
  user: CollabUser;
  /** The socket was refused after the join succeeded (a close in the 44xx
   *  band). The room is already dead; the caller decides what to fall back to. */
  onRefused: (code: number) => void;
}

/** Join, then connect. Rejects with the join's ApiError (401/403/network). */
export async function openCollabRoom({ pageId, role, user, onRefused }: OpenRoomOptions): Promise<CollabRoom> {
  const join = await api.post<CollabJoin>(
    collabJoinPath(pageId),
    { role },
    // A visitor's 401 is a refusal to join, not a lost session.
    { throwOn401: true },
  );
  const doc = new Doc();
  const provider = new WebsocketProvider(collabWsBase(), pageId, doc, {
    params: { session: join.session },
    connect: true,
    disableBc: true,
  });
  const { awareness } = provider;
  awareness.setLocalStateField("user", user);
  awareness.setLocalStateField("role", join.role);
  // Only the server's 44xx band is a refusal; any other close (navigation,
  // a dropped network) is the provider's own reconnect business.
  provider.on("closed", (event) => {
    if (event.code >= 4400 && event.code < 4500) onRefused(event.code);
  });

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    // A null state is the departure frame; the socket is still open here so
    // it goes out before destroy() tears the socket down.
    awareness.setLocalState(null);
    provider.destroy();
    awareness.destroy();
    doc.destroy();
  };
  return {
    pageId,
    session: join.session,
    role: join.role,
    seed: join.seed,
    pageVersion: join.page_version,
    doc,
    provider,
    awareness,
    close,
  };
}

/**
 * The seed rule, from the waiting side.
 *
 * Resolves once the provider has synced AND the document is there to bind:
 * the seeder needs only sync (it is about to write the document itself);
 * everyone else needs the fragment to be non-empty, because a second joiner
 * can sync before the first has seeded, and y-prosemirror never pushes local
 * content into an empty fragment — binding then would show an empty page.
 * `signal` settles it early, so an editor that goes mid-wait does not leave a
 * listener on a destroyed document.
 */
export function whenDocumentReady({ provider, doc, seed }: CollabRoom, signal: AbortSignal): Promise<void> {
  const fragment = doc.getXmlFragment(COLLAB_FRAGMENT);
  return new Promise<void>((resolve) => {
    const settle = () => {
      provider.off("sync", check);
      doc.off("update", check);
      signal.removeEventListener("abort", settle);
      resolve();
    };
    function check() {
      if (provider.synced && (seed || fragment.length > 0)) settle();
    }
    if (signal.aborted) return resolve();
    signal.addEventListener("abort", settle, { once: true });
    provider.on("sync", check);
    doc.on("update", check);
    check();
  });
}
