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

/** An account's `instance_role` (GET /auth/me, the Users page); `global_role` answers in the same
 *  vocabulary for the credential in use. */
export const InstanceRole = { admin: "admin", member: "member" } as const;
export type InstanceRoleValue = (typeof InstanceRole)[keyof typeof InstanceRole];

/** The signed-in user (GET /auth/me). */
export interface Me extends UserRef {
  instance_role: string;
  global_role: string;
  permissions: PermissionValue[];
  manages_teams?: boolean;
  timezone?: string;
  /** Spec 121: a visitor browsing as the Anyone principal, not a signed-in account. */
  anonymous?: boolean;
}

export interface Project {
  id: string;
  key: string;
  name: string;
  /** The current user's effective permission atoms in this project. */
  permissions: PermissionValue[];
}

/** What a `project.settings.page` contribution renders with (RADD-1396): the project whose settings
 *  these are — its `permissions` answer `usePermissions().project(...)` — and the page's segment. */
export interface ProjectSettingsPageProps {
  project: Project;
  path: string;
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
  /** The owning plugin's name (RADD-1389). */
  plugin?: string;
}

/** A plugin UI remote the host should load (from GET /capabilities). */
export interface PluginRemote {
  name: string;
  remote_entry: string;
  ui_api_version: string;
  /** The entity types the remote serves live documents for (the manifest's `live_documents`), so a
   *  document surface can wait for it instead of opening its own editor while the bundle loads. */
  live_documents?: string[];
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
    group?: string;
    requires_admin?: boolean;
  requires_any_project?: string[];
    plugin?: string;
    requires?: PermissionValue[];
    capability?: string;
    order?: number;
  }>;
  plugins: string[];
  remotes?: PluginRemote[];
  /** Plugin-contributed dashboard widget types (the add-widget dropdown lists them). */
  widget_types?: WidgetTypeOption[];
}

/** A plugin-contributed dashboard widget type. A `personal` one shows the viewer's own work, so it
 *  is offered on My Work only (RADD-1393); its plugin draws it through the `dashboard.widget` slot. */
export interface WidgetTypeOption {
  key: string;
  label: string;
  personal?: boolean;
}
