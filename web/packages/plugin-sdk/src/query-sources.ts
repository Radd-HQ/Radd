import { useSyncExternalStore } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import type { EntityMeta } from "./cache";
import { QueryKeyPrefix } from "./query-keys";

/** A data-only contribution. The owner defines its opaque key, wire shape and transport. */
export interface QuerySource<T = unknown> {
  key: string;
  meta?: EntityMeta;
  /** How long a result stays fresh across consumers (default `SOURCE_STALE_MS`). */
  staleTime?: number;
  /** Re-ask while observed — for values that change with the clock (an SLA countdown). */
  refetchInterval?: number;
  fetch: (args: Record<string, unknown>, signal: AbortSignal) => Promise<T>;
}
interface Entry { plugin: string; generation: number; source: QuerySource }
/** A source that names no `staleTime`: long enough that two consumers of one key share a fetch. */
const SOURCE_STALE_MS = 30_000;
const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
let generation = 0;
/** Bumped on every change: a stable snapshot for consumers that read several keys. */
let version = 0;
function changed() { version++; for (const listener of listeners) listener(); }
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

/** ONE query identity per (owner activation, key, args) — shared by every consumer below, and the
 * `[QueryKeyPrefix.pluginQuery, owner]` prefix is what the host loader drops when the owner withdraws. */
function sourceQuery<T>(key: string, args: Record<string, unknown>, entry: Entry | undefined, enabled: boolean) {
  return {
    queryKey: [QueryKeyPrefix.pluginQuery, entry?.plugin ?? null, entry?.generation ?? 0, key, args],
    meta: entry?.source.meta,
    enabled,
    staleTime: entry?.source.staleTime ?? SOURCE_STALE_MS,
    refetchInterval: entry?.source.refetchInterval,
    // Consumers of one source+arguments share this query, and TanStack keeps ONE queryFn per
    // query — whichever consumer rendered last. So it must not depend on a consumer's `enabled`:
    // a disabled consumer's function would otherwise fail the enabled one on the next invalidation.
    queryFn: ({ signal }: { signal: AbortSignal }) => {
      if (!entry) throw new Error("This query source is unavailable");
      return entry.source.fetch(args, signal) as Promise<T>;
    },
  };
}

/** Consumers of one source and arguments share a cached result; the owner's generation is in the key,
 *  so a re-registered source starts fresh. Unavailable is distinct from empty. */
export function useContributedQuery<T>(key: string, args: Record<string, unknown> = {}, { enabled = true } = {}) {
  const entry = useSyncExternalStore(subscribe, () => entries.get(key));
  const active = enabled && Boolean(entry);
  const result = useQuery<T>(sourceQuery<T>(key, args, entry, active));
  // A disabled consumer neither shows the shared result nor asks for a new one.
  const refetch: typeof result.refetch = (options) => active ? result.refetch(options) : Promise.resolve(result);
  return { ...result, refetch, available: Boolean(entry), data: active && !result.isError ? result.data : undefined };
}

export interface ContributedQueryRequest { key: string; args: Record<string, unknown> }
export interface ContributedQueryResult<T> { available: boolean; data: T | undefined; isPending: boolean; isError: boolean }

/** Several sources (or one source over several argument sets) at once, each with exactly the
 * identity `useContributedQuery` gives it — so the two share results — and the same lifetime: an
 * absent source asks nothing, a withdrawn owner's in-flight read is aborted (RADD-1394, the item
 * attribute batches). Callers pass distinct requests; results are aligned with them. */
export function useContributedQueries<T>(requests: readonly ContributedQueryRequest[]): ContributedQueryResult<T>[] {
  useSyncExternalStore(subscribe, () => version);
  const resolved = requests.map((request) => entries.get(request.key));
  const results = useQueries({
    queries: requests.map((request, index) => sourceQuery<T>(request.key, request.args, resolved[index], Boolean(resolved[index]))),
  });
  return results.map((result, index) => {
    const available = Boolean(resolved[index]);
    return {
      available,
      data: available && !result.isError ? result.data : undefined,
      isPending: available && result.isPending,
      isError: available && result.isError,
    };
  });
}
