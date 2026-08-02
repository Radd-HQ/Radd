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
  status: RemoteStatusValue;
  module?: PluginModule;
  error?: string;
}

const loaded = new Map<string, LoadedRemote>();

/** Diagnostics: the current load state of every remote the host has seen. */
export function remoteStates(): LoadedRemote[] {
  return [...loaded.values()];
}

function buildContext(name: string): PluginContext {
  return {
    plugin: name,
    registerSlot: (slot, contribution) => registerSlot(slot, contribution, { plugin: name }),
  };
}

async function loadRemote(remote: PluginRemote): Promise<void> {
  const { name, remote_entry: entry, ui_api_version: version } = remote;
  if (!isUiApiCompatible(version)) {
    console.warn(
      `[radd] plugin "${name}" UI (ui_api_version=${version}) is incompatible with this host — not loaded`,
    );
    loaded.set(name, { name, status: RemoteStatus.incompatible, error: `ui_api_version ${version}` });
    return;
  }
  try {
    const imported = (await import(/* @vite-ignore */ entry)) as
      | PluginModule
      | { default?: PluginModule };
    // A remote may `export default definePlugin({...})` (the common case) or export `activate`
    // as a named export — accept either.
    const mod = ("default" in imported && imported.default ? imported.default : imported) as PluginModule;
    if (!Array.isArray(mod.contributions) && typeof mod.activate !== "function") {
      throw new Error("remote entry exports neither `contributions` nor `activate`");
    }
    const ctx = buildContext(name);
    // Declarative contributions first (the manifest style), then the imperative escape hatch.
    for (const [i, c] of (mod.contributions ?? []).entries()) {
      const { slot, id, ...rest } = c;
      ctx.registerSlot(slot, { id: id ?? `${slot}#${i}`, ...rest });
    }
    if (typeof mod.activate === "function") await mod.activate(ctx);
    loaded.set(name, { name, status: RemoteStatus.loaded, module: mod });
    console.info(`[radd] plugin UI "${name}" loaded`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[radd] plugin UI "${name}" failed to load (quarantined):`, error);
    loaded.set(name, { name, status: RemoteStatus.errored, error: message });
  }
}

function unloadRemote(name: string): void {
  const entry = loaded.get(name);
  if (entry?.module?.deactivate) {
    try {
      entry.module.deactivate(buildContext(name));
    } catch (error) {
      console.error(`[radd] plugin UI "${name}" deactivate() threw:`, error);
    }
  }
  unregisterPlugin(name);
  loaded.delete(name);
}

/**
 * Reconcile loaded remotes with the ENABLED set from the manifest. Idempotent — safe to call on
 * every capabilities change. Returns when all newly-enabled remotes have settled.
 */
export async function syncPluginRemotes(remotes: PluginRemote[] | undefined): Promise<void> {
  const enabled = new Map((remotes ?? []).map((r) => [r.name, r]));

  // Unload remotes that are no longer enabled (disable → live unmount).
  for (const name of [...loaded.keys()]) {
    if (!enabled.has(name)) unloadRemote(name);
  }

  // Load newly-enabled remotes (skip ones already loaded/quarantined this session).
  const toLoad = [...enabled.values()].filter((r) => !loaded.has(r.name));
  await Promise.all(toLoad.map(loadRemote));
}

/** Force a reload of a single remote (e.g. after a disable→enable cycle). */
export async function reloadPluginRemote(remote: PluginRemote): Promise<void> {
  unloadRemote(remote.name);
  await loadRemote(remote);
}
