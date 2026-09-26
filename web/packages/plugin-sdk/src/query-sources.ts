import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";

/** A data-only contribution. The owner defines its opaque key, wire shape and transport. */
export interface QuerySource<T = unknown> {
  key: string;
  meta?: Record<string, unknown>;
  /** How long a result stays fresh across consumers (default 30 s). */
  staleTime?: number;
  fetch: (args: Record<string, unknown>, signal: AbortSignal) => Promise<T>;
}
interface Entry { plugin: string; generation: number; source: QuerySource }
const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
let generation = 0;
function changed() { for (const listener of listeners) listener(); }
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }

/** The loader scopes registration to an activation; another owner cannot replace its contract. */
export function registerQuerySource(plugin: string, source: QuerySource): void {
  if (!source.key || typeof source.fetch !== "function") throw new Error("Invalid contributed query source");
  if (!source.key.startsWith(`${plugin}.`)) throw new Error("Query source keys must be namespaced by their plugin");
  const previous = entries.get(source.key);
  if (previous && previous.plugin !== plugin) throw new Error(`Query source ${source.key} is already owned by ${previous.plugin}`);
  entries.set(source.key, { plugin, source, generation: ++generation });
  changed();
}
export function unregisterQuerySources(plugin: string): void {
  let removed = false;
  for (const [key, entry] of entries) if (entry.plugin === plugin) { entries.delete(key); removed = true; }
  if (removed) changed();
}

/** Consumers of the same source and arguments share one cached result (RADD-1373 — a
 * per-mount identity used to refetch the 2,305-label catalog on every automation-editor mount).
 * The owner's registration generation is in the key, so a re-registered source starts fresh; the
 * host loader drops a withdrawn owner's entries. Unavailable is distinct from an empty result.
 */
export function useContributedQuery<T>(key: string, args: Record<string, unknown> = {}, { enabled = true } = {}) {
  const entry = useSyncExternalStore(subscribe, () => entries.get(key));
  const active = enabled && Boolean(entry);
  const result = useQuery<T>({
    queryKey: ["plugin-query", entry?.plugin ?? null, entry?.generation ?? 0, key, args],
    meta: entry?.source.meta,
    enabled: active,
    staleTime: entry?.source.staleTime ?? 30_000,
    // Consumers of one source+arguments share this query, and TanStack keeps ONE queryFn per
    // query — whichever consumer rendered last. So it must not depend on a consumer's `enabled`:
    // a disabled consumer's function would otherwise fail the enabled one on the next invalidation.
    queryFn: ({ signal }) => {
      if (!entry) throw new Error("This query source is unavailable");
      return entry.source.fetch(args, signal) as Promise<T>;
    },
  });
  // A disabled consumer neither shows the shared result nor asks for a new one.
  const refetch: typeof result.refetch = (options) => active ? result.refetch(options) : Promise.resolve(result);
  return { ...result, refetch, available: Boolean(entry), data: active && !result.isError ? result.data : undefined };
}
