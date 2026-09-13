import { useMemo, useSyncExternalStore } from "react";
import type { Awareness } from "y-protocols/awareness";
import { EMPTY_PRESENCE, presenceSnapshot, type PresenceSnapshot } from "./model";

/**
 * Awareness → React (spec 122). One external store per awareness instance:
 * the snapshot is rebuilt on the awareness `change` event and cached, so
 * `useSyncExternalStore` sees a stable reference between changes and the
 * header strip re-renders when the room changes, not when the caret moves.
 * (Caret moves arrive as `update`, not `change` — `change` fires only when a
 * client's state differs, and the model ignores the cursor field anyway.)
 */
interface PresenceStore {
  subscribe: (onChange: () => void) => () => void;
  getSnapshot: () => PresenceSnapshot;
}

const EMPTY_STORE: PresenceStore = {
  subscribe: () => () => {},
  getSnapshot: () => EMPTY_PRESENCE,
};

function createPresenceStore(awareness: Awareness, selfUserId: string | null): PresenceStore {
  let snapshot = presenceSnapshot(awareness.getStates(), selfUserId);
  const listeners = new Set<() => void>();
  const onChange = () => {
    snapshot = presenceSnapshot(awareness.getStates(), selfUserId);
    for (const listener of listeners) listener();
  };
  return {
    subscribe: (listener) => {
      if (listeners.size === 0) awareness.on("change", onChange);
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) awareness.off("change", onChange);
      };
    },
    getSnapshot: () => snapshot,
  };
}

/** Everyone in the room, and who saves. Empty while there is no room. */
export function usePresence(awareness: Awareness | null, selfUserId: string | null): PresenceSnapshot {
  const store = useMemo(
    () => (awareness ? createPresenceStore(awareness, selfUserId) : EMPTY_STORE),
    [awareness, selfUserId],
  );
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}
