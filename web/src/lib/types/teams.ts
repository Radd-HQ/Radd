/** Teams, directory/LDAP sync + import, and global grants (specs 84/85/87/88). */
import type { UserSourceValue } from "./users";
/** One instance-wide role grant (spec 87): exactly one of user_id/team_id.
 * Roles otherwise only attach to projects, which is why every global-scope atom
 * was ungrantable to a non-admin before this existed. */
export interface GlobalGrant {
  id: string;
  role_id: string;
  user_id: string | null;
  team_id: string | null;
  /** A directory group holding the role instance-wide (RADD-832). */
  group_id: string | null;
}

/** GET /teams (spec 01; ownership — spec 87). RADD-829 retired the directory
 * link: a team is always local, and reaches the directory by holding a GROUP
 * as a member (see RaddGroup / TeamGroup). */
export interface Team {
  id: string;
  name: string;
  created_at: string;
  owner_id: string | null;
  managers: string[];
  /** Resolved server-side: owner ∪ manager ∪ global-atom holder. The client
   * never re-derives it — per-team delegation isn't visible in the permission union. */
  can_manage: boolean;
  can_delete: boolean;
}

export interface TeamCreate {
  name: string;
  owner_id?: string;
}

/** PUT /teams/{id}/managers (spec 87) — full replace, owner-gated. */
export interface TeamManagersUpdate {
  user_ids: string[];
}

/** GET /teams/{id}/members (RADD-829): direct rows plus group-carried people —
 * `via_group` names the carrier (null = a direct user row). */
export interface TeamMember {
  user_id: string;
  email: string;
  name: string;
  via_group: string | null;
}

/** One mirrored directory group — GET /groups (RADD-829). */
export interface RaddGroup {
  id: string;
  dn: string;
  name: string;
  directory_missing_since: string | null;
  direct_member_count: number;
  /** RADD-833: what a grant on this group RESOLVES to (nesting included). */
  transitive_member_count?: number;
  parent_names?: string[];
  child_names?: string[];
}

/** GET /groups/{id}/reach — how many people a grant on the group resolves to,
 * nesting included (RADD-832). The guardrail number shown before a grant saves. */
export interface GroupReach {
  group_id: string;
  user_count: number;
}

/** A GROUP member of a team — GET /teams/{id}/groups (RADD-829). */
export interface TeamGroup {
  group_id: string;
  name: string;
  dn: string;
  directory_missing_since: string | null;
}

/** One AD group from GET /ldap/groups (spec 84). member_count is the DIRECT
 * member-attribute length (display only — the sync resolves nested members). */
export interface DirectoryGroup {
  cn: string;
  dn: string;
  description: string;
  member_count: number;
}

/** One directory user from GET /ldap/directory-users (spec 84). */
export interface DirectoryUser {
  username: string;
  email: string;
  name: string;
}

/** POST /ldap/groups/import (spec 84). */
export interface GroupImportRequest {
  group_dns: string[];
  provision_members: boolean;
}

export interface GroupImportResult {
  group_dn: string;
  cn: string;
  team_id: string | null;
  created: boolean;
  members_added: number;
  users_provisioned: number;
  error: string | null;
}

/** POST /ldap/directory-users/import (spec 84). */
/** Why an incoming AD user was tied to an existing account (spec 88). Radd has
 * no username column — identity is the email — so an AD sAMAccountName can only
 * be compared against the local part of one. */
export const ImportMatchKind = {
  email: "email",
  username: "username",
  name: "name",
} as const;
export type ImportMatchKindValue = (typeof ImportMatchKind)[keyof typeof ImportMatchKind];

/** What importing one AD user would run into (spec 88). */
export const ImportStatus = {
  new: "new",
  linked: "linked",
  conflict: "conflict",
} as const;
export type ImportStatusValue = (typeof ImportStatus)[keyof typeof ImportStatus];

/** What to do about it (spec 88). Overwrite and merge both end with AD as the
 * source of truth; they differ in how many Radd accounts are involved. */
export const ImportResolution = {
  create: "create",
  skip: "skip",
  overwrite: "overwrite",
  merge: "merge",
} as const;
export type ImportResolutionValue = (typeof ImportResolution)[keyof typeof ImportResolution];

export interface ExistingMatch {
  user_id: string;
  email: string;
  name: string;
  source: UserSourceValue;
  active: boolean;
  kind: ImportMatchKindValue;
}

/** One row of POST /ldap/directory-users/import/preview (spec 88). */
export interface ImportCandidate {
  username: string;
  email: string;
  name: string;
  status: ImportStatusValue;
  matches: ExistingMatch[];
  suggested: ImportResolutionValue;
}

export interface ImportResolutionEntry {
  email: string;
  resolution: ImportResolutionValue;
  target_user_id?: string | null;
}

export interface DirectoryUserImportRequest {
  emails: string[];
  /** Spec 88: per-person conflict decisions. Omitted = create-or-link, existing
   * accounts untouched (the pre-88 behavior). */
  resolutions?: ImportResolutionEntry[];
}

export interface DirectoryUserImportResult {
  email: string;
  user_id: string | null;
  created: boolean;
  resolution: ImportResolutionValue;
  merged_user_id: string | null;
  error: string | null;
}

/** POST /teams/{id}/directory-sync (spec 84) — what the reconcile changed. */
export interface DirectorySyncResult {
  added: number;
  removed: number;
}

/** POST /ldap/sync/users (spec 85) — what one user-sync pass did. */
export interface UserSyncResult {
  provisioned: number;
  updated: number;
  deactivated: number;
  errors: string[];
}

/** One directory_sync_state row (spec 85). `last_result` is the run summary —
 * user_sync: {provisioned, updated, deactivated, errors}, group_sync:
 * {groups, added, removed, errors} (RADD-829 reshaped it). */
export interface DirectorySyncState {
  kind: string;
  last_run_at: string;
  last_result: Record<string, unknown>;
}

/** GET /ldap/sync-status (spec 85) — both rows (null = never ran). */
export interface DirectorySyncStatus {
  user_sync: DirectorySyncState | null;
  group_sync: DirectorySyncState | null;
}

/** project↔team attachment; role is data-driven since spec 06. */
export interface ProjectTeam {
  project_id: string;
  team_id: string;
  role_id: string;
  /** The role's key, hydrated for display. */
  role: string;
}

