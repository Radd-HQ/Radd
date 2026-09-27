/**
 * The host runtime loader for plugin UI (spec 94; docs/plugin-platform.md §8b-A; RADD-1373).
 *
 * Two kinds of plugin UI, one registration path:
 *   - BUNDLED core plugins (`STATIC_PLUGINS`): compiled into the host and registered at boot, before
 *     the first render, so their pickers and pages never show a loading gap. They are withdrawn only
 *     if the server stops loading the plugin (a module left out of RADD_MODULES) and re-registered
 *     when it returns.
 *   - REMOTE optional plugins: on every capabilities change, the ENABLED remotes are diffed against
 *     what is loaded — a new remote is version-gated, `import()`ed and activated; a removed one is
 *     deactivated and unregistered, so its slots vanish live. A remote that fails to load is
 *     QUARANTINED: logged, marked errored, and skipped.
 * While any remote is loading, `setRemotesLoading(true)` lets an empty `Slot` render its `pending`
 * state instead of its "unavailable" fallback, and `setLiveDocumentsArriving` names the entity types
 * a loading remote declares live documents for, so their surfaces wait for it rather than open the
 * editor whose draft the arriving session would replace (RADD-1461).
 */
import type { QueryClient } from "@tanstack/react-query";
import {
  isUiApiCompatible,
  registerSlot,
  registerDataSource,
  registerLiveDocumentSource,
  registerQuerySource, registerCommandSource, unregisterCommandSources,
  setLiveDocumentsArriving,
  setRemotesLoading,
  unregisterQuerySources,
  unregisterDataSources,
  unregisterLiveDocumentSources,
  unregisterPlugin,
  type PluginContext,
  type PluginModule,
  type PluginRemote,
} from "@radd/plugin-sdk";
import { STATIC_PLUGINS } from "../plugins/static.generated";

const RemoteStatus = {
  loading: "loading",
  loaded: "loaded",
  errored: "errored",
  incompatible: "incompatible",
} as const;
type RemoteStatusValue = (typeof RemoteStatus)[keyof typeof RemoteStatus];

interface LoadedRemote {
  name: string;
  identity: string;
  status: RemoteStatusValue;
  module?: PluginModule;
  error?: string;
  cancelled: boolean;
  pending?: Promise<void>;
  /** The entity types this remote DECLARES live documents for (the manifest's `live_documents`);
   *  while it loads, their surfaces wait for it instead of opening their own editor (RADD-1461). */
  liveDocuments: readonly string[];
}

/** Optional plugins' remotes, by plugin name. */
const loaded = new Map<string, LoadedRemote>();
/** Core plugins' bundled UI currently registered, by plugin name. */
const statics = new Map<string, LoadedRemote>();
/** False until the first capabilities answer names the enabled remotes. */
let synced = false;
let queryClient: QueryClient | null = null;

interface RemoteState { name: string; status: RemoteStatusValue; error?: string }
let states: RemoteState[] = [];
const listeners = new Set<() => void>();
function publish() {
  states = [...loaded.values()].map(({ name, status, error }) => ({ name, status, error }));
  const loading = [...loaded.values()].filter((entry) => entry.status === RemoteStatus.loading);
  setRemotesLoading(!synced || loading.length > 0);
  // Only a remote still LOADING holds a document surface back; one that failed or was refused is
  // gone, and the surface runs its own editor as if the plugin were off.
  setLiveDocumentsArriving(synced, loading.flatMap((entry) => entry.liveDocuments));
  for (const listener of listeners) listener();
}
export function readRemoteStates(): RemoteState[] { return states; }
export function subscribeRemoteStates(listener: () => void): () => void {
  listeners.add(listener); return () => { listeners.delete(listener); };
}
async function bounded<T>(operation: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([operation, new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error("Plugin UI took too long to load")), 30_000);
    })]);
  } finally { clearTimeout(timer); }
}

/** A core plugin whose UI is bundled with the host — never loaded, awaited or failed as a remote. */
export const isBundledPlugin = (name: string): boolean => name in STATIC_PLUGINS;

const identity = (remote: PluginRemote) => JSON.stringify([remote.remote_entry, remote.ui_api_version]);

/** The query cache a withdrawn plugin's data is dropped from (set once by the host at boot). */
export function bindQueryClient(client: QueryClient): void { queryClient = client; }

function buildContext(entry: LoadedRemote, current: () => boolean): PluginContext {
  // A registration that lands after disable/replacement cannot add stale UI.
  const live = () => !entry.cancelled && current();
  return {
    plugin: entry.name,
    registerCommandSource: (source) => { if (live()) registerCommandSource(entry.name, source); },
    registerQuerySource: (source) => { if (live()) registerQuerySource(entry.name, source); },
    registerDataSource: (source) => { if (live()) registerDataSource(entry.name, source); },
    registerLiveDocumentSource: (source) => { if (live()) registerLiveDocumentSource(entry.name, source); },
    registerSlot: (slot, contribution) => { if (live()) registerSlot(slot, contribution, { plugin: entry.name }); },
  };
}

/** Everything a plugin contributed, gone — its slots, sources, commands, live-document sessions
 *  (their consumers close them) and cached queries. */
function withdraw(name: string): void {
  unregisterPlugin(name);
  unregisterDataSources(name);
  unregisterLiveDocumentSources(name);
  unregisterQuerySources(name);
  unregisterCommandSources(name);
  // Contributed query sources key on ["plugin-query", owner, …], and a plugin's own queries by
  // convention on its name; both are dropped so a re-enable reads fresh. Queries keyed otherwise
  // (a core plugin sharing a host key) simply refetch when stale — and a core plugin is absent only
  // when the server was started without it, so it never returns mid-session.
  queryClient?.removeQueries({ queryKey: ["plugin-query", name] });
  queryClient?.removeQueries({ queryKey: [name] });
}

async function deactivate(entry: LoadedRemote, current: () => boolean): Promise<void> {
  try {
    await entry.module?.deactivate?.(buildContext(entry, current));
  } catch (error) {
    console.error(`[radd] plugin UI "${entry.name}" deactivate() failed:`, error);
  }
}

/** Register a module's declared contributions synchronously; then run its activation. */
async function activate(entry: LoadedRemote, mod: PluginModule, current: () => boolean): Promise<void> {
  entry.module = mod;
  if (!Array.isArray(mod.contributions) && !Array.isArray(mod.dataSources) && !Array.isArray(mod.querySources)
    && !Array.isArray(mod.commandSources) && !Array.isArray(mod.liveDocuments) && typeof mod.activate !== "function") {
    throw new Error("plugin UI exports no contributions, data sources, query sources, live documents or activation");
  }
  const ctx = buildContext(entry, current);
  for (const [i, c] of (mod.contributions ?? []).entries()) {
    const { slot, id, ...rest } = c;
    ctx.registerSlot(slot, { id: id ?? `${slot}#${i}`, ...rest });
  }
  for (const source of mod.commandSources ?? []) ctx.registerCommandSource(source);
  for (const source of mod.querySources ?? []) ctx.registerQuerySource(source);
  for (const source of mod.dataSources ?? []) ctx.registerDataSource(source);
  for (const source of mod.liveDocuments ?? []) ctx.registerLiveDocumentSource(source);
  await bounded(Promise.resolve(mod.activate?.(ctx)));
}

async function loadRemote(remote: PluginRemote, entry: LoadedRemote): Promise<void> {
  const { name, remote_entry: url, ui_api_version: version } = remote;
  const current = () => loaded.get(name) === entry;
  if (!isUiApiCompatible(version)) {
    entry.status = RemoteStatus.incompatible;
    entry.error = `ui_api_version ${version}`;
    publish();
    return;
  }
  try {
    const imported = (await bounded(import(/* @vite-ignore */ url))) as PluginModule | { default?: PluginModule };
    if (entry.cancelled) return;
    const mod = ("default" in imported && imported.default ? imported.default : imported) as PluginModule;
    await activate(entry, mod, current);
    if (entry.cancelled) {
      await deactivate(entry, current);
      return;
    }
    entry.status = RemoteStatus.loaded;
    publish();
  } catch (error) {
    if (current()) withdraw(name);
    entry.cancelled = true;
    entry.status = RemoteStatus.errored;
    entry.error = error instanceof Error ? error.message : String(error);
    publish();
    await deactivate(entry, current);
    console.error(`[radd] plugin UI "${name}" failed to load:`, entry.error);
  }
}

/**
 * Register the bundled core plugins the server loads (`enabled` = the capabilities' plugin list;
 * omitted at boot, before it is known, which registers them all). Idempotent: a plugin already
 * registered is left alone, one the server dropped is withdrawn, one that returns is registered
 * afresh.
 */
export function syncStaticPlugins(enabled?: readonly string[]): void {
  for (const [name, mod] of Object.entries(STATIC_PLUGINS)) {
    const wanted = enabled === undefined || enabled.includes(name);
    const current = statics.get(name);
    if (!wanted && current) {
      current.cancelled = true;
      statics.delete(name);
      withdraw(name);
      void deactivate(current, () => false);
    } else if (wanted && !current) {
      const entry: LoadedRemote = { name, identity: "bundled", status: RemoteStatus.loaded, cancelled: false, liveDocuments: [] };
      statics.set(name, entry);
      activate(entry, mod, () => statics.get(name) === entry).catch((error) => {
        console.error(`[radd] bundled plugin UI "${name}" failed to activate:`, error);
      });
    }
  }
}

/** Reconcile the optional remotes immediately, including in-flight loads. Changed URLs reload;
 * failed entries remain quarantined until replacement or disable/re-enable. */
export async function syncPluginRemotes(remotes: PluginRemote[] | undefined): Promise<void> {
  if (remotes === undefined) return;
  synced = true;
  // A bundled plugin is never also loaded as a remote: its UI is already registered.
  const enabled = new Map(remotes.filter((r) => !isBundledPlugin(r.name)).map((r) => [r.name, r]));
  const cleanup: Promise<void>[] = [];
  for (const [name, entry] of loaded) {
    const next = enabled.get(name);
    if (!next || identity(next) !== entry.identity) {
      entry.cancelled = true;
      withdraw(name);
      loaded.delete(name);
      // In-flight activation owns its eventual cleanup; do not deactivate twice.
      if (!entry.pending) cleanup.push(deactivate(entry, () => false));
    }
  }
  for (const remote of enabled.values()) {
    if (loaded.has(remote.name)) continue;
    const entry: LoadedRemote = {
      name: remote.name, identity: identity(remote), status: RemoteStatus.loading, cancelled: false,
      liveDocuments: remote.live_documents ?? [],
    };
    loaded.set(remote.name, entry);
    entry.pending = loadRemote(remote, entry).finally(() => { entry.pending = undefined; });
  }
  publish();
  await Promise.all([...cleanup, ...[...loaded.values()].map((entry) => entry.pending)]);
}

publish();
