/**
 * The PUBLIC data contract a plugin's UI compiles against (docs/plugin-platform.md §9). A curated,
 * stable subset of Radd's entities — NOT the host's internal `web/src/lib/types.ts`, which a plugin
 * (especially an external one) cannot import. Structurally compatible with the wire shapes.
 */

/** A permission atom, e.g. "item.update". Plugins gate UI on these via `usePermissions`. */
export type PermissionValue = string;

export interface UserRef {
  id: string;
  name: string;
  email?: string;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
}

/** The signed-in user (GET /auth/me). */
export interface Me extends UserRef {
  instance_role: string;
  global_role: string;
  permissions: PermissionValue[];
  manages_teams?: boolean;
  timezone?: string;
}

export interface Project {
  id: string;
  key: string;
  name: string;
  /** The current user's effective permission atoms in this project. */
  permissions: PermissionValue[];
}

export interface StateRef {
  id: string;
  name: string;
  category?: string;
}

/**
 * An issue/work item. The commonly-needed fields are typed; anything else is reachable via the
 * index signature (as `unknown`, cast at the use site) so a plugin isn't blocked by a field the
 * public contract hasn't surfaced yet.
 */
export interface Item {
  id: string;
  project_id: string;
  key: string;
  number: number;
  title: string;
  state: StateRef;
  assignee?: UserRef | null;
  reporter?: UserRef | null;
  created_at?: string;
  updated_at?: string;
  [extra: string]: unknown;
}

/** The permission checker `usePermissions()` returns. */
export interface Permissions {
  /** Holds the atom in the GLOBAL union (off /auth/me). */
  global: (atom: PermissionValue) => boolean;
  /** Holds the atom in a specific project (off Project.permissions). */
  project: (project: Pick<Project, "permissions">, atom: PermissionValue) => boolean;
}

/** One capability descriptor from GET /capabilities. */
export interface Capability {
  key: string;
  label: string;
  category: string;
  enabled: boolean;
  detail?: Record<string, unknown>;
}

/** A plugin UI remote the host should load (from GET /capabilities). */
export interface PluginRemote {
  name: string;
  remote_entry: string;
  ui_api_version: string;
}

/** The backend-assembled UI manifest (GET /capabilities). */
export interface CapabilitiesManifest {
  capabilities: Capability[];
  nav: Array<{
    key: string;
    label: string;
    path: string;
    icon?: string;
    section?: string;
    requires?: PermissionValue[];
    capability?: string;
    order?: number;
  }>;
  plugins: string[];
  remotes?: PluginRemote[];
}
