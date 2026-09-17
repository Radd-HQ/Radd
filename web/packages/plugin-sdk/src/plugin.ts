import type { SlotContribution, SlotIdValue } from "./slots";

/**
 * The contract every plugin remote's entry exports (docs/plugin-platform.md §8b-A). The host
 * runtime loader `import()`s the remote and applies its contributions, auto-tagged with the plugin's
 * name (from the backend manifest) so disabling the plugin removes exactly its UI.
 *
 * Two authoring styles — prefer the DECLARATIVE one:
 *   - `contributions`: an array where each row is one attachment `{ slot, ...contribution }`. Every
 *     place the plugin touches the UI is visible at a glance — this reads like a manifest.
 *   - `activate(ctx)`: an imperative escape hatch for conditional/dynamic registration.
 */
export interface PluginContext {
  /** The stable plugin name (matches the backend manifest / enable key). */
  plugin: string;
  /** Register a slot contribution, auto-tagged with this plugin. */
  registerSlot: (slot: SlotIdValue | string, contribution: SlotContribution) => void;
}

/** One row of the declarative `contributions` manifest: a slot + what to put in it. `id` is
 *  optional (defaults to `<slot>#<index>`). */
export interface PluginContribution extends Omit<SlotContribution, "id"> {
  slot: SlotIdValue | string;
  id?: string;
}

export interface PluginModule {
  /** Declarative: every UI attachment in one place (preferred). */
  contributions?: PluginContribution[];
  /** Imperative escape hatch, for dynamic/conditional registration. */
  activate?: (ctx: PluginContext) => void | Promise<void>;
  deactivate?: (ctx: PluginContext) => void | Promise<void>;
}

/** Identity helper for type-checking a remote's entry module. */
export function definePlugin(mod: PluginModule): PluginModule {
  return mod;
}
