import type { Doc } from "yjs";
import type { Awareness } from "y-protocols/awareness";
import { api } from "../../../lib/api";
import { COLLAB_AUTOSAVE_MS, apiPagePath } from "../../../lib/constants";
import type { Page, PageUpdate } from "../../../lib/types";
import { electSaver } from "./model";

/**
 * The elected saver (spec 122).
 *
 * Every editor runs one of these; only the one the election names actually
 * writes. It serialises the markdown the editor already produces (the listener
 * fires for remote transactions too, so `getMarkdown` is always the shared
 * document, not this tab's typing) and PATCHes it with `collab_session` —
 * never `expected_version`: the room is the concurrency control now.
 *
 * Triggers: 1.5 s after the last change (local or remote); the tab going
 * hidden; becoming the saver (covers whatever the previous saver had pending
 * when it left); and `final` when this client leaves the room. On a real
 * unload the effect cleanup may not run, so `pagehide` sends the final write
 * with keepalive.
 */
export interface SaverOptions {
  pageId: string;
  session: string;
  doc: Doc;
  awareness: Awareness;
  getMarkdown: () => string;
  onSaved?: (page: Page) => void;
  onError?: (error: unknown) => void;
}

export interface Saver {
  /** Write now if this client is the saver (`final` writes even if unchanged). */
  flush: (final?: boolean) => Promise<void>;
  /** Detach; with `final`, the last write goes out first. */
  stop: (final: boolean) => Promise<void>;
}

export function startSaver({
  pageId,
  session,
  doc,
  awareness,
  getMarkdown,
  onSaved,
  onError,
}: SaverOptions): Saver {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastSaved: string | null = null;
  let inflight: Promise<void> | null = null;
  let stopped = false;
  let wasSaver = false;

  const isSaver = () => electSaver(awareness.getStates()) === awareness.clientID;

  const body = (markdown: string, final: boolean): PageUpdate => ({
    body: markdown,
    collab_session: session,
    final,
  });

  const write = async (final: boolean) => {
    const markdown = getMarkdown();
    if (!final && markdown === lastSaved) return;
    try {
      const page = await api.patch<Page>(apiPagePath(pageId), body(markdown, final));
      lastSaved = markdown;
      onSaved?.(page);
    } catch (error) {
      onError?.(error);
    }
  };

  const flush = async (final = false) => {
    clearTimeout(timer);
    timer = undefined;
    if (stopped || !isSaver()) return;
    // One write at a time, in order: a second flush during a request waits
    // for it, then sends the newer markdown.
    const previous = inflight ?? Promise.resolve();
    inflight = previous.then(() => write(final));
    await inflight;
  };

  const schedule = () => {
    if (stopped) return;
    clearTimeout(timer);
    timer = setTimeout(() => void flush(), COLLAB_AUTOSAVE_MS);
  };

  const onDocUpdate = () => schedule();
  const onAwarenessChange = () => {
    const now = isSaver();
    if (now && !wasSaver) schedule();
    wasSaver = now;
  };
  const onVisibility = () => {
    if (document.visibilityState === "hidden") void flush();
  };
  const onPageHide = () => {
    if (stopped || !isSaver()) return;
    // Best effort: the page is going away, so this cannot be awaited.
    void api.patch<Page>(apiPagePath(pageId), body(getMarkdown(), true), { keepalive: true }).catch(() => {});
  };

  doc.on("update", onDocUpdate);
  awareness.on("change", onAwarenessChange);
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("pagehide", onPageHide);
  wasSaver = isSaver();

  return {
    flush,
    stop: async (final) => {
      if (stopped) return;
      if (final) await flush(true);
      stopped = true;
      clearTimeout(timer);
      doc.off("update", onDocUpdate);
      awareness.off("change", onAwarenessChange);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onPageHide);
    },
  };
}
