import { useSyncExternalStore } from "react";
import { useQueries, type QueryClient } from "@tanstack/react-query";

/** Semantic decoration, supplied by a feature without teaching the host its vocabulary. */
export interface StatusIndicator {
  id: string;
  label: string;
  title: string;
  ariaLabel: string;
  tone: "neutral" | "warning" | "danger" | "success";
  dim?: boolean;
  /** Plain-text picker suffix; optional because not every status needs one. */
  textSuffix?: string;
}
export interface PersonIndicator extends StatusIndicator { personId: string }
export interface TimesheetAnnotation extends StatusIndicator {
  personId: string;
  start: string;
  end: string;
  suppressOutlier: boolean;
}
export interface DataContracts {
  personIndicators: { args: Record<string, never>; result: PersonIndicator[] };
  timesheetAnnotations: { args: { start: string; end: string }; result: TimesheetAnnotation[] };
}
export type DataKind = keyof DataContracts;
export type DataSource<K extends DataKind = DataKind> = {
  [P in K]: {
    kind: P;
    id: string;
    staleTime?: number;
    refetchInterval?: number;
    fetch: (args: DataContracts[P]["args"], signal: AbortSignal) => Promise<DataContracts[P]["result"]>;
  }
}[K];
type Entry = { plugin: string; generation: number; source: DataSource };
let entries: Entry[] = [];
let generation = 0;
const listeners = new Set<() => void>();
const snapshots = new Map<DataKind, Entry[]>();
function changed() { snapshots.clear(); for (const notify of listeners) notify(); }
function snapshot(kind: DataKind): Entry[] {
  if (!snapshots.has(kind)) snapshots.set(kind, entries.filter(e => e.source.kind === kind));
  return snapshots.get(kind)!;
}
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }

/** Registration is scoped by the loader, including late/failed activation protection. */
export function registerDataSource(plugin: string, source: DataSource): void {
  entries = entries.filter(e => !(e.plugin === plugin && e.source.kind === source.kind && e.source.id === source.id));
  entries.push({ plugin, generation: ++generation, source });
  changed();
}
export function unregisterDataSources(plugin: string): void {
  entries = entries.filter(e => e.plugin !== plugin);
  changed();
}

/** Every observer shares queries, while each activation gets a fresh cache identity.
 * Removing a source removes its observers/data immediately and aborts unused requests.
 * An unavailable source contributes nothing; its errors cannot break the host page.
 */
export function usePluginData<K extends DataKind>(kind: K, args: DataContracts[K]["args"], actorId: string | undefined): DataContracts[K]["result"] {
  const sources = useSyncExternalStore(subscribe, () => snapshot(kind));
  const queries = useQueries({ queries: sources.map(entry => ({
    queryKey: ["plugin-data", entry.plugin, entry.generation, kind, entry.source.id, actorId, args],
    queryFn: ({ signal }: { signal: AbortSignal }) => {
      const source = entry.source as DataSource<K>;
      // The discriminated source kind and its contract args are paired at this API boundary.
      return (source.fetch as (args: DataContracts[K]["args"], signal: AbortSignal) => Promise<DataContracts[K]["result"]>)(args, signal);
    },
    enabled: Boolean(actorId),
    staleTime: entry.source.staleTime ?? 30_000,
    refetchInterval: entry.source.refetchInterval,
    gcTime: 0,
  })) });
  return (actorId ? queries.flatMap((query, index) => (query.data ?? []).map(value => ({ ...value, id: `${sources[index].plugin}/${sources[index].source.id}/${value.id}` }))) : []) as DataContracts[K]["result"];
}

/** A feature mutation refreshes its contributions without knowing their consumers. */
export function invalidatePluginData(client: QueryClient, plugin: string): Promise<void> {
  return client.invalidateQueries({ queryKey: ["plugin-data", plugin] });
}
