import { useMemo, useSyncExternalStore } from "react";
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
interface Entry { plugin: string; generation: number; source: CommandSource }
let entries: Entry[] = [];
let generation = 0;
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => { listeners.add(listener); return () => {listeners.delete(listener);}; };
const changed = () => { for (const listener of listeners) listener(); };
export function registerCommandSource(plugin: string, source: CommandSource): void {
  if (!source.id || !source.entityType || typeof source.list !== "function" || typeof source.execute !== "function") throw new Error("Invalid command source");
  entries = [...entries.filter(entry => entry.plugin !== plugin || entry.source.id !== source.id), {plugin, source, generation: ++generation}];
  changed();
}
export function unregisterCommandSources(plugin: string): void {
  entries = entries.filter(entry => entry.plugin !== plugin);
  changed();
}
/** Run a command. A menu may retain a rendered callback, so a withdrawn provider is refused BEFORE
 * anything starts; once started, a command is a write and runs to completion — withdrawing its
 * provider must not abort a request the server may already have acted on (RADD-1373). */
async function execute(entry: Entry, id: string, context: CommandContext): Promise<void> {
  if (!entries.includes(entry)) throw new Error("This command is no longer available");
  await entry.source.execute(id, context, new AbortController().signal);
}
export function useContributedCommands(context: CommandContext, enabled = true): ContributedCommand[] {
  const all = useSyncExternalStore(subscribe, () => entries);
  const sources = all.filter(entry => entry.source.entityType === context.entityType);
  const client = useQueryClient();
  const results = useQueries({queries: sources.map(entry => ({
    queryKey: ["plugin-commands", entry.plugin, entry.generation, entry.source.id, context, enabled],
    queryFn: ({signal}: {signal: AbortSignal}) => {
      if (!enabled || !entries.includes(entry)) throw new Error("Command discovery is unavailable");
      return entry.source.list(context, signal);
    }, meta: entry.source.meta, enabled, staleTime: 0,
  }))});
  return useMemo(() => !enabled ? [] : results.flatMap((result, index) => result.isError ? [] : (result.data ?? []).map(command => ({
    ...command, id: `${sources[index].plugin}/${sources[index].source.id}/${command.id}`,
    run: async () => {await execute(sources[index], command.id, context); await client.invalidateQueries();},
  }))), [all, enabled, context.entityType, context.entityId, context.projectId, results, client]);
}

export function invalidatePluginCommands(client: QueryClient, plugin: string): Promise<void> {
  return client.invalidateQueries({queryKey: ["plugin-commands", plugin]});
}
