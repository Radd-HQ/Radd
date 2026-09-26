/**
 * The host runtime loader for plugin UI remotes (spec 94; docs/plugin-platform.md §8b-A).
 *
 * On boot (and whenever the capabilities manifest changes — e.g. a plugin is enabled/disabled in
 * the admin), it diffs the ENABLED remotes against what's loaded:
 *   - new remote  → version-gate (`ui_api_version` major vs the host SDK) → `import()` the bundle →
 *                   call its `activate(ctx)`, which registers its slot contributions.
 *   - removed remote → call `deactivate` (if any) + `unregisterPlugin(name)` so its slots vanish
 *                   from every `<Slot>` live (unmount without a reload).
 * A remote that fails to load/activate (or is version-incompatible) is QUARANTINED: logged, marked
 * errored, and skipped — it never aborts boot or blocks other remotes.
 */
import {
  isUiApiCompatible,
  registerSlot,
  registerDataSource,
  registerQuerySource, registerCommandSource, unregisterCommandSources,
  unregisterQuerySources,
  unregisterDataSources,
  unregisterPlugin,
  type PluginContext,
  type PluginModule,
  type PluginRemote,
} from "@radd/plugin-sdk";

export const RemoteStatus = {
  loading: "loading",
  loaded: "loaded",
  errored: "errored",
  incompatible: "incompatible",
} as const;
export type RemoteStatusValue = (typeof RemoteStatus)[keyof typeof RemoteStatus];

interface LoadedRemote {
  name: string;
  identity: string;
  status: RemoteStatusValue;
  module?: PluginModule;
  error?: string;
  cancelled: boolean;
  pending?: Promise<void>;
}

const loaded = new Map<string, LoadedRemote>();
export interface RemoteState { name: string; status: RemoteStatusValue; error?: string }
let states: RemoteState[] = [];
const listeners = new Set<() => void>();
function publish() {
  states = [...loaded.values()].map(({ name, status, error }) => ({ name, status, error }));
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

const identity = (remote: PluginRemote) => JSON.stringify([remote.remote_entry, remote.ui_api_version]);

function buildContext(entry: LoadedRemote): PluginContext {
  return {
    plugin: entry.name,
    registerCommandSource: source => {
      if (!entry.cancelled && loaded.get(entry.name) === entry) registerCommandSource(entry.name, source);
    },
    registerQuerySource: source => {
      if (!entry.cancelled && loaded.get(entry.name) === entry) registerQuerySource(entry.name, source);
    },
    registerDataSource: (source) => {
      if (!entry.cancelled && loaded.get(entry.name) === entry) registerDataSource(entry.name, source);
    },
    registerSlot: (slot, contribution) => {
      // An activation that finished after disable/replacement cannot add stale UI.
      if (!entry.cancelled && loaded.get(entry.name) === entry) {
        registerSlot(slot, contribution, { plugin: entry.name });
      }
    },
  };
}

async function deactivate(entry: LoadedRemote): Promise<void> {
  try {
    await entry.module?.deactivate?.(buildContext(entry));
  } catch (error) {
    console.error(`[radd] plugin UI "${entry.name}" deactivate() failed:`, error);
  }
}

async function loadRemote(remote: PluginRemote, entry: LoadedRemote): Promise<void> {
  const { name, remote_entry: url, ui_api_version: version } = remote;
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
    entry.module = mod;
    if (!Array.isArray(mod.contributions) && !Array.isArray(mod.dataSources) && !Array.isArray(mod.querySources) && !Array.isArray(mod.commandSources) && typeof mod.activate !== "function") {
      throw new Error("remote entry exports no contributions, data sources, query sources or activation");
    }
    const ctx = buildContext(entry);
    for (const [i, c] of (mod.contributions ?? []).entries()) {
      const { slot, id, ...rest } = c;
      ctx.registerSlot(slot, { id: id ?? `${slot}#${i}`, ...rest });
    }
    for (const source of mod.commandSources ?? []) ctx.registerCommandSource(source);
    for (const source of mod.querySources ?? []) ctx.registerQuerySource(source);
    for (const source of mod.dataSources ?? []) ctx.registerDataSource(source);
    await bounded(Promise.resolve(mod.activate?.(ctx)));
    if (entry.cancelled) {
      await deactivate(entry);
      return;
    }
    entry.status = RemoteStatus.loaded;
    publish();
  } catch (error) {
    if (loaded.get(name) === entry) { unregisterPlugin(name); unregisterDataSources(name); unregisterQuerySources(name); unregisterCommandSources(name); }
    entry.cancelled = true;
    entry.status = RemoteStatus.errored;
    entry.error = error instanceof Error ? error.message : String(error);
    publish();
    await deactivate(entry);
    console.error(`[radd] plugin UI "${name}" failed to load:`, entry.error);
  }
}

/** Reconcile immediately, including in-flight loads. Changed URLs reload; failed
 * entries remain quarantined until replacement or disable/re-enable. */
export async function syncPluginRemotes(remotes: PluginRemote[] | undefined): Promise<void> {
  const enabled = new Map((remotes ?? []).map((r) => [r.name, r]));
  const cleanup: Promise<void>[] = [];
  for (const [name, entry] of loaded) {
    const next = enabled.get(name);
    if (!next || identity(next) !== entry.identity) {
      entry.cancelled = true;
      unregisterPlugin(name);
      unregisterDataSources(name); unregisterQuerySources(name); unregisterCommandSources(name);
      loaded.delete(name);
      // In-flight activation owns its eventual cleanup; do not deactivate twice.
      if (!entry.pending) cleanup.push(deactivate(entry));
    }
  }
  for (const remote of enabled.values()) {
    if (loaded.has(remote.name)) continue;
    const entry: LoadedRemote = {
      name: remote.name, identity: identity(remote), status: RemoteStatus.loading, cancelled: false,
    };
    loaded.set(remote.name, entry);
    entry.pending = loadRemote(remote, entry).finally(() => { entry.pending = undefined; });
  }
  publish();
  await Promise.all([...cleanup, ...[...loaded.values()].map((entry) => entry.pending)]);
}
