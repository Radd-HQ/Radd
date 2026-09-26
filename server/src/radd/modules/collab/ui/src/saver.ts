import type { Doc } from "yjs";
import type { Awareness } from "y-protocols/awareness";
import type { LiveSave } from "@radd/plugin-sdk";
import { COLLAB_AUTOSAVE_MS } from "./constants";
import { electSaver } from "./model";

/**
 * The elected saver (spec 122): every editor runs one; only the elected one writes, handing the
 * shared markdown (`getMarkdown` is the shared doc, remote edits included) to the page's own save
 * with the session as voucher — never `expected_version`. Triggers: 1.5 s after any change, tab
 * hidden, becoming saver (covers the previous saver's pending edit), leaving (`final`); `pagehide`
 * sends the final write with keepalive, since the session's close may not run on unload.
 */
interface SaverOptions {
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
