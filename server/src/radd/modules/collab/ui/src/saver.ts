import type { Doc } from "yjs";
import type { Awareness } from "y-protocols/awareness";
import type { LiveSave } from "@radd/plugin-sdk";
import { COLLAB_AUTOSAVE_MS } from "./constants";
import { electSaver } from "./model";

/**
 * The elected saver (spec 122).
 *
 * Every editor runs one of these; only the one the election names actually
 * writes. It reads the markdown the editor already produces (a bound editor
 * publishes remote changes too, so `getMarkdown` is always the shared
 * document, not this tab's typing) and hands it to the DOCUMENT's own write
 * path with the session as its voucher — never `expected_version`: the room is
 * the concurrency control now. The saver decides when; the page decides how
 * (RADD-1397: the collab plugin knows no page endpoint).
 *
 * Triggers: 1.5 s after the last change (local or remote); the tab going
 * hidden; becoming the saver (covers whatever the previous saver had pending
 * when it left); and `final` when this client leaves the room. On a real
 * unload the session's own close may not run, so `pagehide` sends the final
 * write with keepalive.
 */
export interface SaverOptions {
  session: string;
  doc: Doc;
  awareness: Awareness;
  getMarkdown: () => string;
  save: (markdown: string, save: LiveSave) => Promise<void>;
}

export interface Saver {
  /** Write now if this client is the saver (`final` writes even if unchanged). */
  flush: (final?: boolean) => Promise<void>;
  /** Detach; with `final`, the last write goes out first. */
  stop: (final: boolean) => Promise<void>;
}

export function startSaver({ session, doc, awareness, getMarkdown, save }: SaverOptions): Saver {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lastSaved: string | null = null;
  let inflight: Promise<void> | null = null;
  let stopped = false;
  let wasSaver = false;

  const isSaver = () => electSaver(awareness.getStates()) === awareness.clientID;

  const write = async (final: boolean) => {
    const markdown = getMarkdown();
    if (!final && markdown === lastSaved) return;
    try {
      await save(markdown, { session, final, keepalive: false });
      lastSaved = markdown;
    } catch {
      // The document's save reported it; the next change tries again.
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
    void save(getMarkdown(), { session, final: true, keepalive: true }).catch(() => {});
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
