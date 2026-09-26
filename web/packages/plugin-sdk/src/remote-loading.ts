import { useSyncExternalStore } from "react";

/**
 * Whether any plugin UI bundle is still loading (RADD-1373). The host loader
 * reports it; `Slot` reads it so an empty slot says nothing while its
 * contributor may still arrive, instead of rendering its "unavailable"
 * fallback for the length of a network round trip. Core plugins are bundled
 * with the host and registered at boot, so only optional remotes are ever
 * pending.
 */
let loading = false;
const listeners = new Set<() => void>();

export function setRemotesLoading(next: boolean): void {
  if (next === loading) return;
  loading = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useRemotesLoading(): boolean {
  return useSyncExternalStore(subscribe, () => loading, () => loading);
}
