import type { Awareness } from "y-protocols/awareness";
import { EMPTY_PRESENCE, presenceSnapshot, type PresenceSnapshot } from "./model";

/**
 * Awareness → React (spec 122), one store per SESSION: it follows whichever
 * room the session is in (a rejoin attaches the new one), and the chrome — who
 * is here, who saves — subscribes to it with `useSyncExternalStore`. The
 * snapshot is rebuilt on the awareness `change` event and cached, so the
 * header re-renders when the room changes, not when the caret moves. (Caret
 * moves arrive as `update`, not `change` — `change` fires only when a client's
 * state differs, and the model ignores the cursor field anyway.)
 */
interface PresenceView extends PresenceSnapshot {
  /** This client's awareness id while it is in a room, else null. */
  self: number | null;
}

export interface PresenceStore {
  subscribe: (onChange: () => void) => () => void;
  getSnapshot: () => PresenceView;
  attach: (awareness: Awareness) => void;
  detach: () => void;
}

const DETACHED: PresenceView = { ...EMPTY_PRESENCE, self: null };

export function createPresenceStore(selfUserId: string): PresenceStore {
  const listeners = new Set<() => void>();
  let awareness: Awareness | null = null;
  let snapshot = DETACHED;
  const refresh = () => {
    snapshot = awareness
      ? { ...presenceSnapshot(awareness.getStates(), selfUserId), self: awareness.clientID }
      : DETACHED;
    for (const listener of listeners) listener();
  };
  return {
    subscribe: (listener) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    getSnapshot: () => snapshot,
    attach: (next) => {
      awareness?.off("change", refresh);
      awareness = next;
      next.on("change", refresh);
      refresh();
    },
    detach: () => {
      if (!awareness) return;
      awareness.off("change", refresh);
      awareness = null;
      refresh();
    },
  };
}
