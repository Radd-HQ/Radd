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
  unregisterPlugin,
  type PluginContext,
  type PluginModule,
  type PluginRemote,
} from "@radd/plugin-sdk";

export const RemoteStatus = {
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
const identity = (remote: PluginRemote) => JSON.stringify([remote.remote_entry, remote.ui_api_version]);

function buildContext(entry: LoadedRemote): PluginContext {
  return {
    plugin: entry.name,
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
    return;
  }
  try {
    const imported = (await import(/* @vite-ignore */ url)) as PluginModule | { default?: PluginModule };
    if (entry.cancelled) return;
    const mod = ("default" in imported && imported.default ? imported.default : imported) as PluginModule;
    entry.module = mod;
    if (!Array.isArray(mod.contributions) && typeof mod.activate !== "function") {
      throw new Error("remote entry exports neither contributions nor activate");
    }
    const ctx = buildContext(entry);
    for (const [i, c] of (mod.contributions ?? []).entries()) {
      const { slot, id, ...rest } = c;
      ctx.registerSlot(slot, { id: id ?? `${slot}#${i}`, ...rest });
    }
    await mod.activate?.(ctx);
    if (entry.cancelled) {
      await deactivate(entry);
      return;
    }
    entry.status = RemoteStatus.loaded;
  } catch (error) {
    if (loaded.get(name) === entry) unregisterPlugin(name);
    entry.cancelled = true;
    entry.status = RemoteStatus.errored;
    entry.error = error instanceof Error ? error.message : String(error);
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
      loaded.delete(name);
      // In-flight activation owns its eventual cleanup; do not deactivate twice.
      if (!entry.pending) cleanup.push(deactivate(entry));
    }
  }
  for (const remote of enabled.values()) {
    if (loaded.has(remote.name)) continue;
    const entry: LoadedRemote = {
      name: remote.name, identity: identity(remote), status: RemoteStatus.loaded, cancelled: false,
    };
    loaded.set(remote.name, entry);
    entry.pending = loadRemote(remote, entry).finally(() => { entry.pending = undefined; });
  }
  await Promise.all([...cleanup, ...[...loaded.values()].map((entry) => entry.pending)]);
}
