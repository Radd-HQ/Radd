/** Plugin platform + capabilities manifest types (specs 93/94). */
/** The backend-assembled UI manifest (spec 93 / A7): capability flags + plugin
 * nav items. The shell renders the nav alongside its builtin nav, gating each item
 * by `requires` against the user's atoms — so an enabled plugin's nav appears with
 * no edit to the shell (chokepoint 3). */
interface PluginNavItem {
  key: string;
  label: string;
  path: string;
  icon: string;
  section: string;
  group?: string;
  requires_admin?: boolean;
  requires_any_project?: string[];
  plugin?: string;
  requires: string[];
  capability: string;
  order: number;
}
interface CapabilityFlag {
  key: string;
  label: string;
  category: string;
  enabled: boolean;
  /** Plugin-specific detail; `summary` is the one line Server status shows (RADD-1389). */
  detail: Record<string, unknown>;
  /** The owning plugin's name — what a status row links through. */
  plugin?: string;
}
export interface CapabilitiesManifest {
  capabilities: CapabilityFlag[];
  nav: PluginNavItem[];
  /** Names of every currently-enabled plugin — lets the SPA hide UI for a disabled
   * optional plugin (e.g. the issue view's contributed rail sections). */
  plugins: string[];
  /** Each enabled plugin's UI remote to load at runtime (spec 94, module federation). */
  remotes: PluginRemoteRef[];
  /** Plugin-contributed pluggable types (spec 94) — the create-view / add-widget dropdowns list these. */
  view_types: ViewTypeOption[];
  widget_types: PluginTypeOption[];
}

/** A plugin-contributed view/widget type: its stored key + the label a create-UI shows (spec 94). */
interface PluginTypeOption {
  key: string;
  label: string;
}

/** A view type the host's LIST draws over the owning plugin's rows (RADD-1396): `rows_path`
 *  answers the `/items` paging contract in the plugin's order; `columns` seed a new view. */
export interface ViewListSurface {
  rows_path: string;
  columns: string[];
  refresh_seconds: number;
}

/** A plugin-contributed view type (spec 94). Without `list_surface` its plugin draws it through
 *  the `view.type` slot; `sidebar_section` lists its views in a section of their own, with live
 *  counts, instead of among the ordinary views (RADD-1396). `icon` names a `lib/icons.ts` entry. */
export interface ViewTypeOption extends PluginTypeOption {
  icon?: string;
  list_surface?: ViewListSurface | null;
  sidebar_section?: string;
}

/** A plugin UI remote the host runtime loader imports (spec 94). */
interface PluginRemoteRef {
  name: string;
  remote_entry: string;
  ui_api_version: string;
}

/** A plugin's lifecycle row from the plugin manager (spec 93 / A4). Core plugins
 * are always enabled and locked (`can_toggle: false`); non-core cycle through
 * discovered → installed → enabled ⇄ disabled → uninstalled. */
/** One evaluated CapabilitySpec on a plugin row — `enabled` is runtime
 * configured-ness (a connector's env token present), not lifecycle state. */
interface PluginCapability {
  key: string;
  label: string;
  category: string;
  enabled: boolean;
}

export interface Plugin {
  id: string;
  name: string;
  version: string;
  core: boolean;
  state: string;
  description: string;
  can_toggle: boolean;
  active: boolean;
  runtime_state?: "enabled" | "disabled" | "applying" | "error";
  /** Failures to apply THIS plugin. A process that cannot reconcile at all is
   * reported once, by GET /plugins/runtime (RADD-1372). */
  runtime_errors?: string[];
  pending_processes?: number;
  origin: string;
  dependencies: string[];
  problems: string[];
  managed: boolean;
  capabilities: PluginCapability[];
}

/** One process's acknowledgement row (GET /plugins/runtime). */
export interface PluginProcessReport {
  process: string;
  stale: boolean;
  /** This process could not reconcile at all — not a failure of any one plugin. */
  error?: string | null;
}
