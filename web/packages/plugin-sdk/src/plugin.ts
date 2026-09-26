import type { CommandSource } from "./commands";
import type { QuerySource } from "./query-sources";
import type { DataSource } from "./data";
import type { LiveDocumentSource } from "./live-documents";
import type { SlotContribution, SlotIdValue } from "./slots";

/** What a plugin remote's entry exports. The loader applies it tagged with the plugin's name, so
 *  disabling the plugin removes exactly its UI. Prefer declarative `contributions`; `activate` is the
 *  escape hatch for dynamic registration. */
export interface PluginContext {
  /** The stable plugin name (matches the backend manifest / enable key). */
  plugin: string;
  registerCommandSource: (source: CommandSource) => void;
  registerQuerySource: (source: QuerySource) => void;
  registerDataSource: (source: DataSource) => void;
  /** Provide live sessions for one entity type's documents (RADD-1397). */
  registerLiveDocumentSource: (source: LiveDocumentSource) => void;
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
  dataSources?: DataSource[];
  querySources?: QuerySource[];
  commandSources?: CommandSource[];
  /** Live sessions for documents (RADD-1397): withdrawn with the plugin, closing open sessions. */
  liveDocuments?: LiveDocumentSource[];
  /** Imperative escape hatch, for dynamic/conditional registration. */
  activate?: (ctx: PluginContext) => void | Promise<void>;
  deactivate?: (ctx: PluginContext) => void | Promise<void>;
}

/** Identity helper for type-checking a remote's entry module. */
export function definePlugin(mod: PluginModule): PluginModule {
  return mod;
}
