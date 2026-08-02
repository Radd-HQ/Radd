/** Plugin platform + capabilities manifest types (specs 93/94). */
/** The backend-assembled UI manifest (spec 93 / A7): capability flags + plugin
 * nav items. The shell renders the nav alongside its builtin nav, gating each item
 * by `requires` against the user's atoms — so an enabled plugin's nav appears with
 * no edit to the shell (chokepoint 3). */
export interface PluginNavItem {
  key: string;
  label: string;
  path: string;
  icon: string;
  section: string;
  requires: string[];
  capability: string;
  order: number;
}
export interface CapabilityFlag {
  key: string;
  label: string;
  category: string;
  enabled: boolean;
  detail: Record<string, unknown>;
}
export interface CapabilitiesManifest {
  capabilities: CapabilityFlag[];
  nav: PluginNavItem[];
  /** Names of every currently-enabled plugin — lets the SPA hide UI for a disabled
   * optional plugin (e.g. the issue view's Participants/Approvals/CSAT sections). */
  plugins: string[];
  /** Each enabled plugin's UI remote to load at runtime (spec 94, module federation). */
  remotes: PluginRemoteRef[];
  /** Plugin-contributed pluggable types (spec 94) — the create-view / add-widget dropdowns list these. */
  view_types: PluginTypeOption[];
  widget_types: PluginTypeOption[];
}

/** A plugin-contributed view/widget type: its stored key + the label a create-UI shows (spec 94). */
export interface PluginTypeOption {
  key: string;
  label: string;
}

/** A plugin UI remote the host runtime loader imports (spec 94). */
export interface PluginRemoteRef {
  name: string;
  remote_entry: string;
  ui_api_version: string;
}

/** A plugin's lifecycle row from the plugin manager (spec 93 / A4). Core plugins
 * are always enabled and locked (`can_toggle: false`); non-core cycle through
 * discovered → installed → enabled ⇄ disabled → uninstalled. */
/** One evaluated CapabilitySpec on a plugin row — `enabled` is runtime
 * configured-ness (a connector's env token present), not lifecycle state. */
export interface PluginCapability {
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
  capabilities: PluginCapability[];
}
