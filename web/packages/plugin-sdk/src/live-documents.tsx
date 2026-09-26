import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import type { EditorBinding } from "./editor-extensions";
import { useCurrentUser } from "./hooks";
import { ContributionFrame } from "./slots";

/**
 * Live documents: a document surface asks whether a live session exists for what it shows, and a
 * plugin's `LiveDocumentSource` (`definePlugin({ liveDocuments })`) answers. The surface owns the
 * document (endpoint, body, Save); the session owns presence, the editor binding, and when and by
 * which client the shared copy is saved. Without a provider the answer is `none` and the surface
 * runs its single-editor flow; withdrawing the plugin closes every session, last save first.
 */

export const LiveStatus = {
  /** No live session: the document's own flow (Save, with its version check). */
  none: "none",
  /** A session is being opened. */
  joining: "joining",
  live: "live",
} as const;
export type LiveStatusValue = (typeof LiveStatus)[keyof typeof LiveStatus];

/** What the viewer is in a session. An observer is present; only an editor changes the copy. */
export const LiveRole = { editor: "editor", observer: "observer" } as const;
export type LiveRoleValue = (typeof LiveRole)[keyof typeof LiveRole];

/** How the session vouches for a save the document's owner makes. */
export interface LiveSave {
  /** The session's token — the owner's write guard accepts it in place of a version check. */
  session: string;
  /** The session's last save. */
  final: boolean;
  /** The page is going away: the request must outlive it. */
  keepalive: boolean;
}

/** What a document surface asks. Re-sent every render; only its identity fields reopen a session. */
export interface LiveDocumentRequest {
  entityType: string;
  entityId: string;
  /** The viewer holds write access to the document. */
  canWrite: boolean;
  /** The viewer is editing it (an editor session); otherwise they are reading (an observer). */
  editing: boolean;
  /** The editor's markdown now — read when the session saves, never a captured value. */
  getMarkdown: () => string;
  /** Write `markdown` as the session's save, through the document's own write path. Resolves
   *  once written; rejects with a presentable error. */
  save: (markdown: string, save: LiveSave) => Promise<void>;
}

/** Who is asking — always a signed-in account: a visitor never joins a session. */
export interface LiveViewer {
  id: string;
  name: string;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
}

/** What a source is asked to open. */
export interface LiveDocumentOpen extends LiveDocumentRequest {
  viewer: LiveViewer;
}

/** A session's state, pushed by its source whenever it changes. */
export interface LiveDocumentState {
  /** `unavailable` hands the document back to its ordinary flow (refused, or cannot exist). */
  status: "joining" | "live" | "unavailable";
  role: LiveRoleValue | null;
  /** An editor's binding, once the session can be edited. */
  binding: EditorBinding | null;
  /** Who is here, for the document's header — rendered for readers too. */
  presence?: ReactNode;
  /** Beside the editor's Done: how the shared copy is being saved. */
  saving?: ReactNode;
}

export interface LiveDocumentHandle {
  /** The session's last save, when it is this client's to make; resolves once written. */
  finish: () => Promise<void>;
  /** Leave. Idempotent; a last save still owed goes out first. */
  close: () => void;
}

/** A provider of live sessions for one entity type. */
export interface LiveDocumentSource {
  /** `<plugin>.<name>`, like every contributed source. */
  id: string;
  /** The documents it serves ("page"). One source per entity type. */
  entityType: string;
  open: (request: LiveDocumentOpen, update: (state: LiveDocumentState) => void) => LiveDocumentHandle;
}

/** The answer a surface renders from. */
export interface LiveDocument {
  status: LiveStatusValue;
  role: LiveRoleValue | null;
  binding: EditorBinding | null;
  presence: ReactNode;
  saving: ReactNode;
  /** The last save before leaving edit mode (Done); resolves at once without a session. */
  finish: () => Promise<void>;
}

interface Entry { plugin: string; generation: number; source: LiveDocumentSource }
const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
let generation = 0;
function changed() { for (const listener of listeners) listener(); }
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }

/** The loader scopes registration to an activation. One provider per entity type. */
export function registerLiveDocumentSource(plugin: string, source: LiveDocumentSource): void {
  if (!source.entityType || typeof source.open !== "function") throw new Error("Invalid live document source");
  if (!source.id?.startsWith(`${plugin}.`)) throw new Error("Live document source ids must be namespaced by their plugin");
  const previous = entries.get(source.entityType);
  if (previous && previous.plugin !== plugin) {
    throw new Error(`Live ${source.entityType} documents are already provided by ${previous.plugin}`);
  }
  entries.set(source.entityType, { plugin, source, generation: ++generation });
  changed();
}

export function unregisterLiveDocumentSources(plugin: string): void {
  let removed = false;
  for (const [key, entry] of entries) if (entry.plugin === plugin) { entries.delete(key); removed = true; }
  if (removed) changed();
}

const NONE: LiveDocument = {
  status: LiveStatus.none, role: null, binding: null, presence: null, saving: null, finish: async () => undefined,
};

/**
 * The live session for a document while the surface shows it (`null` = stay out). It reopens when
 * the document, editing intent, write access or viewer changes, and closes on unmount or
 * withdrawal. No provider is `none` at once, even while bundles load: an optional plugin must never
 * hold up the document's own editor. A provider that arrives mid-edit opens its session then (the
 * surface keeps its draft, which seeds an empty shared copy).
 */
export function useLiveDocument(request: LiveDocumentRequest | null): LiveDocument {
  const entityType = request?.entityType ?? "";
  const entry = useSyncExternalStore(subscribe, () => entries.get(entityType));
  const me = useCurrentUser();
  const viewer: LiveViewer | null = me && !me.anonymous
    ? { id: me.id, name: me.name, avatar_color: me.avatar_color ?? null, avatar_emoji: me.avatar_emoji ?? null }
    : null;
  const latest = useRef(request);
  latest.current = request;
  const handle = useRef<LiveDocumentHandle | null>(null);

  const identity = request && viewer && entry
    ? [entry.generation, request.entityType, request.entityId, request.canWrite, request.editing,
        viewer.id, viewer.name, viewer.avatar_color, viewer.avatar_emoji]
    : null;
  const key = identity ? JSON.stringify(identity) : null;
  const [held, setHeld] = useState<{ key: string; state: LiveDocumentState } | null>(null);

  useEffect(() => {
    if (!key || !entry || !request || !viewer) return;
    let current = true;
    const open: LiveDocumentOpen = {
      entityType: request.entityType,
      entityId: request.entityId,
      canWrite: request.canWrite,
      editing: request.editing,
      viewer,
      // The latest request's functions, so a surface's re-render never reopens the session.
      getMarkdown: () => latest.current?.getMarkdown() ?? "",
      save: (markdown, save) => latest.current
        ? latest.current.save(markdown, save)
        : Promise.reject(new Error("The document was closed")),
    };
    let opened: LiveDocumentHandle;
    try {
      opened = entry.source.open(open, (state) => { if (current) setHeld({ key, state }); });
    } catch (error) {
      console.error(`[radd-plugin-sdk] live ${request.entityType} session from "${entry.plugin}" failed to open`, error);
      setHeld({ key, state: { status: "unavailable", role: null, binding: null } });
      return;
    }
    handle.current = opened;
    return () => {
      current = false;
      if (handle.current === opened) handle.current = null;
      try { opened.close(); } catch (error) { console.error("[radd-plugin-sdk] a live session failed to close", error); }
    };
    // `key` carries every value the session was opened with; the functions are read through `latest`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const finish = useCallback(() => handle.current?.finish() ?? Promise.resolve(), []);
  const state = held && held.key === key ? held.state : null;
  const plugin = entry?.plugin ?? null;
  return useMemo<LiveDocument>(() => {
    if (!key || state?.status === "unavailable") return NONE;
    const frame = (node: ReactNode) => (node && plugin ? <ContributionFrame plugin={plugin}>{node}</ContributionFrame> : null);
    return {
      status: state?.status === "live" ? LiveStatus.live : LiveStatus.joining,
      role: state?.role ?? null,
      binding: state?.binding ?? null,
      presence: frame(state?.presence),
      saving: frame(state?.saving),
      finish,
    };
  }, [key, state, plugin, finish]);
}
