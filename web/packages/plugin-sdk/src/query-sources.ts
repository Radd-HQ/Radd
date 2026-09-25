import { useId, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";

/** A data-only contribution. The owner defines its opaque key, wire shape and transport. */
export interface QuerySource<T = unknown> {
  key: string;
  meta?: Record<string, unknown>;
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

/** Each mounted consumer owns its request. Source/argument/enabled changes remove the old
 * observer, aborting unused work; every activation gets fresh data. Unavailable is distinct
 * from an empty successful result. The consumer retains its saved references independently.
 */
export function useContributedQuery<T>(key: string, args: Record<string, unknown> = {}, { enabled = true } = {}) {
  const entry = useSyncExternalStore(subscribe, () => entries.get(key));
  const session = useId();
  const active = enabled && Boolean(entry);
  const result = useQuery<T>({
    queryKey: ["plugin-query", entry?.plugin ?? null, entry?.generation ?? 0, key, args, session, enabled],
    meta: entry?.source.meta,
    enabled: active,
    gcTime: 0, staleTime: 0, retry: false,
    queryFn: ({ signal }) => {
      if (!active || !entry) throw new Error("This query source is unavailable or disabled");
      return entry.source.fetch(args, signal) as Promise<T>;
    },
  });
  return { ...result, available: Boolean(entry), data: active && !result.isError ? result.data : undefined };
}
