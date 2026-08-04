/** Permissions + roles-as-data (spec 06). */
// ---------------------------------------------------------------------------
// Permissions + roles-as-data (spec 06)
// ---------------------------------------------------------------------------

/** Mirror of the backend `Permission` enum (GET /permissions catalog keys). */
export const Permission = {
  globalManage: "global.manage",
  projectCreate: "project.create",
  projectManage: "project.manage",
  itemRead: "item.read",
  itemCreate: "item.create",
  itemUpdate: "item.update",
  /** Spec 22: log work + manage your own worklogs (project-scoped). */
  worklogWrite: "worklog.write",
  /** Spec 22: see other people's timesheets across the server (global). */
  timesheetView: "timesheet.view",
  commentWrite: "comment.write",
  /** RADD-790: attaching a file is its own authority, not item.update — a role
   *  that may discuss an issue without editing it can still add the crash log.
   *  `item.update` implies it, so nothing that could attach before cannot now. */
  attachmentCreate: "attachment.create",
  attachmentDelete: "attachment.delete",
  commentReadInternal: "comment.read_internal",
  viewCreate: "view.create",
  /** Spec 87: administering ANY team. Per-team leaders are granted separately —
   * `Team.can_manage` / `can_delete` carry the resolved answer for one team. */
  teamRead: "team.read",
  teamCreate: "team.create",
  teamUpdate: "team.update",
  teamDelete: "team.delete",
  roleRead: "role.read",
  roleUpdate: "role.update",
  userManage: "user.manage",
  /** RADD-816: the deleted manage umbrellas' work rides the CRUD atoms now. */
  cycleRead: "cycle.read",
  cycleCreate: "cycle.create",
  cycleUpdate: "cycle.update",
  releaseUpdate: "release.update",
  labelRead: "label.read",
  labelUpdate: "label.update",
  cannedRead: "canned.read",
  cannedUpdate: "canned.update",
  slaUpdate: "sla.update",
  /** Spec 20: manage automation rules (global). */
  automationManage: "automation.manage",
  stateManage: "state.manage",
  fieldManage: "field.manage",
  webhookManage: "webhook.manage",
  /** Spec 109: the shared card-layout preset library (global). */
  cardPresetRead: "cardpreset.read",
  cardPresetCreate: "cardpreset.create",
  cardPresetUpdate: "cardpreset.update",
  cardPresetDelete: "cardpreset.delete",
  /** Spec 20: manage a project's intake forms (project-scoped). */
  formManage: "form.manage",
  /** Spec 43 (pages) — SPACE-scoped since RADD-791. They were global because a
   *  page had no scope to be checked against, which made per-space access
   *  inexpressible. Asking `perms.global(pageRead)` is therefore always wrong. */
  pageRead: "page.read",
  pageWrite: "page.write",
  pageManage: "page.manage",
  pageDelete: "page.delete",
  /** Spec 75: the server-wide-broadcast gate on dashboard sharing (global). */
  dashboardCreate: "dashboard.create",
} as const;
// Spec 50: permissions are open-ended data now (77 CRUD atoms + custom roles).
// The named `Permission` const above still autocompletes the ones used in gating;
// `(string & {})` keeps that autocomplete while accepting any catalog key.
export type PermissionValue = (typeof Permission)[keyof typeof Permission] | (string & {});

/** Mirrors `PermissionScope` in `server/src/radd/modules/auth/types.py`.
 *
 * RADD-808: this drifted in BOTH directions and neither side noticed — the
 * server grew `space` (RADD-791) and never appeared here, so the four page
 * atoms were silently dropped from the roles matrix and could not be granted
 * at all. A scope the client does not know is not a type error; it is a row
 * that renders nowhere. `test_permission_scope_contract.py` now pins the two
 * lists together so the next scope fails a test instead of a screen. */
export const PermissionScope = {
  project: "project",
  global: "global",
  /** RADD-791 — checked against a wiki space. */
  space: "space",
} as const;
export type PermissionScopeValue = (typeof PermissionScope)[keyof typeof PermissionScope];

/** One row of GET /permissions — feeds the roles matrix UI. */
export interface PermissionInfo {
  key: PermissionValue;
  description: string;
  scope: PermissionScopeValue;
  /** Spec 50: the resource half of the key (item, state, …) — matrix grouping. */
  resource: string;
  /** Spec 50: the verb half (create/read/update/delete/manage/…) — matrix column. */
  action: string;
}

/** GET /roles (spec 06) — global role registry. Builtin rows are immutable. */
/**
 * The Baseline role's key (RADD-773).
 *
 * The one builtin whose permission set is editable, because it is what every
 * active user holds without being granted anything. It used to be two hardcoded
 * frozensets in the server's `authz.py`, which is why a member could edit any
 * wiki page and delete any cycle while Settings showed nothing to explain it.
 */
export const BASELINE_ROLE_KEY = "baseline";

/** One atom a person holds, and where it came from (RADD-779; provenance
 * widened by RADD-809: channel, scope, backlink to the supplying role). */
export interface PermissionSource {
  permission: string;
  /** "baseline" | "role" | "instance-admin". */
  kind: string;
  role_name: string | null;
  /** Implied by an umbrella rather than ticked on a role. */
  implied: boolean;
  /** Backlink: the supplying role's id (the Baseline row for kind "baseline"). */
  role_id: string | null;
  /** Where the supplying grant applies: "global" | "project" | "space". */
  scope: string;
  /** How the role reached the scope: membership | team | grant | attached. */
  via: string | null;
  /** The team that carried it, when via === "team". */
  via_team: string | null;
  /** Project key / space name for team-view rows that span scopes. */
  scope_label: string | null;
}

/** One spec-92 grant row reaching the inspected subject (RADD-809). */
export interface ResourceAccessRow {
  resource_type: string;
  resource_id: string;
  resource_label: string | null;
  access: string;
  subject_type: string; // user | team | role | group
  subject_id: string;
  subject_name: string | null; // null = the user directly
  project_id: string | null;
  project_key: string | null;
}

/** Grants per registered resource type, with the default the reader needs to
 * interpret an empty list — default-open types are reachable with no rows. */
export interface ResourceTypeAccess {
  resource_type: string;
  label: string;
  default_open: boolean;
  hierarchical: boolean;
  accesses: string[];
  rows: ResourceAccessRow[];
}

export interface AccessSummary {
  readable_projects: number;
  updatable_projects: number;
  total_projects: number;
  readable_spaces: number | null;
  total_spaces: number | null;
}

export interface UserAccess {
  resources: ResourceTypeAccess[];
  summary: AccessSummary;
}

export interface TeamAccess {
  atoms: PermissionSource[];
  resources: ResourceTypeAccess[];
}

export interface Role {
  id: string;
  key: string;
  name: string;
  description: string;
  permissions: PermissionValue[];
  is_builtin: boolean;
  position: number;
  created_at: string;
}

export interface RoleCreate {
  key: string;
  name: string;
  description?: string;
  permissions: PermissionValue[];
}

/** PATCH /roles/{id} — permissions patchable on non-builtin roles only. */
export interface RoleUpdate {
  name?: string;
  description?: string;
  permissions?: PermissionValue[];
}

/** Direct user↔project membership with a data-driven role (spec 06). */
export interface ProjectMember {
  project_id: string;
  user_id: string;
  role_id: string;
  /** The role's key, hydrated for display. */
  role: string;
}

export interface ProjectMemberUpsert {
  user_id: string;
  role_id: string;
}
