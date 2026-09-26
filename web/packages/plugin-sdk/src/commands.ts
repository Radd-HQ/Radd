import { useId, useMemo, useSyncExternalStore } from "react";
import { useQueries, useQueryClient, type QueryClient } from "@tanstack/react-query";

/** Nonvisual commands for contextual menus. The provider owns discovery and execution. */
export interface CommandContext { entityType: string; entityId: string; projectId?: string }
export interface Command { id: string; label: string; hint?: string; keywords?: string }
export interface CommandSource {
  id: string;
  entityType: string;
  meta?: Record<string, unknown>;
  list: (context: CommandContext, signal: AbortSignal) => Promise<Command[]>;
  execute: (commandId: string, context: CommandContext, signal: AbortSignal) => Promise<void>;
}
export interface ContributedCommand extends Command { run: () => Promise<void> }
interface Entry { plugin: string; generation: number; source: CommandSource; pending: Set<AbortController> }
let entries: Entry[] = [];
let generation = 0;
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => { listeners.add(listener); return () => {listeners.delete(listener);}; };
const changed = () => { for (const listener of listeners) listener(); };
function cancel(entry: Entry) { for (const controller of entry.pending) controller.abort(); entry.pending.clear(); }
export function registerCommandSource(plugin: string, source: CommandSource): void {
  if (!source.id || !source.entityType || typeof source.list !== "function" || typeof source.execute !== "function") throw new Error("Invalid command source");
  for (const entry of entries) if (entry.plugin === plugin && entry.source.id === source.id) cancel(entry);
  entries = [...entries.filter(entry => entry.plugin !== plugin || entry.source.id !== source.id), {plugin, source, generation: ++generation, pending: new Set()}];
  changed();
}
export function unregisterCommandSources(plugin: string): void {
  for (const entry of entries) if (entry.plugin === plugin) cancel(entry);
  entries = entries.filter(entry => entry.plugin !== plugin);
  changed();
}
async function execute(entry: Entry, id: string, context: CommandContext): Promise<void> {
  // A menu may retain a previously rendered callback. Never let it invoke a withdrawn provider.
  if (!entries.includes(entry)) throw new Error("This command is no longer available");
  const controller = new AbortController();
  entry.pending.add(controller);
  try {
    await entry.source.execute(id, context, controller.signal);
    if (controller.signal.aborted || !entries.includes(entry)) throw new DOMException("Command provider was withdrawn", "AbortError");
  } finally {entry.pending.delete(controller);}
}
export function useContributedCommands(context: CommandContext, enabled = true): ContributedCommand[] {
  const all = useSyncExternalStore(subscribe, () => entries);
  const sources = all.filter(entry => entry.source.entityType === context.entityType);
  const session = useId();
  const client = useQueryClient();
  const results = useQueries({queries: sources.map(entry => ({
    queryKey: ["plugin-commands", entry.plugin, entry.generation, entry.source.id, context, session, enabled],
    queryFn: ({signal}: {signal: AbortSignal}) => {
      if (!enabled || !entries.includes(entry)) throw new Error("Command discovery is unavailable");
      return entry.source.list(context, signal);
    }, meta: entry.source.meta, enabled, staleTime: 0, gcTime: 0, retry: false,
  }))});
  return useMemo(() => !enabled ? [] : results.flatMap((result, index) => result.isError ? [] : (result.data ?? []).map(command => ({
    ...command, id: `${sources[index].plugin}/${sources[index].source.id}/${command.id}`,
    run: async () => {await execute(sources[index], command.id, context); await client.invalidateQueries();},
  }))), [all, enabled, context.entityType, context.entityId, context.projectId, results, client]);
}

export function invalidatePluginCommands(client: QueryClient, plugin: string): Promise<void> {
  return client.invalidateQueries({queryKey: ["plugin-commands", plugin]});
}
