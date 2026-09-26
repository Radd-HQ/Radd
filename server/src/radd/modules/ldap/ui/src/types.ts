/** The directory plugin's wire vocabulary (specs 84/85/88; its own since RADD-1381). */

export const LdapPath = {
  groups: "/ldap/groups",
  groupsImport: "/ldap/groups/import",
  directoryUsers: "/ldap/directory-users",
  // Spec 88: the dry run classifies a selection against existing accounts first.
  directoryUsersImportPreview: "/ldap/directory-users/import/preview",
  directoryUsersImport: "/ldap/directory-users/import",
  syncStatus: "/ldap/sync-status",
  syncUsers: "/ldap/sync/users",
  syncGroups: "/ldap/sync/groups",
  /** Owned by core modules this plugin depends on (projects, groups). */
  mirroredGroups: "/groups",
  teamGroups: (teamId: string) => `/teams/${teamId}/groups`,
} as const;

export const ldapKeys = {
  groups: (q: string) => ["ldapGroups", { q }] as const,
  directoryUsers: (q: string) => ["ldapDirectoryUsers", { q }] as const,
  syncStatus: ["ldapSyncStatus"] as const,
};

/** Host caches a directory write changes: the people and team lists, and the mirror table. */
export const AffectedKeys = {
  users: ["users"],
  usersAdmin: ["usersAdmin"],
  teams: ["teams"],
  teamMembers: ["teamMembers"],
  groups: ["groups"],
} as const;

/** One AD group from GET /ldap/groups. member_count is the DIRECT member-attribute length. */
export interface DirectoryGroup {
  cn: string;
  dn: string;
  description: string;
  member_count: number;
}

/** A group Radd has mirrored (GET /groups): transitive reach, nesting, directory health. */
export interface MirroredGroup {
  id: string;
  dn: string;
  name: string;
  directory_missing_since: string | null;
  direct_member_count: number;
  transitive_member_count?: number;
  parent_names?: string[];
  child_names?: string[];
}

export interface DirectoryUser {
  username: string;
  email: string;
  name: string;
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

/** Why an incoming AD user was tied to an existing account (spec 88). Radd has no username
 * column — identity is the email — so a sAMAccountName is compared against an email's local part. */
export const ImportMatchKind = { email: "email", username: "username", name: "name" } as const;
export type ImportMatchKindValue = (typeof ImportMatchKind)[keyof typeof ImportMatchKind];

export const ImportStatus = { new: "new", linked: "linked", conflict: "conflict" } as const;
export type ImportStatusValue = (typeof ImportStatus)[keyof typeof ImportStatus];

/** Overwrite and merge both end with AD as the source of truth; they differ in how many Radd
 * accounts are involved. */
export const ImportResolution = { create: "create", skip: "skip", overwrite: "overwrite", merge: "merge" } as const;
export type ImportResolutionValue = (typeof ImportResolution)[keyof typeof ImportResolution];

export interface ExistingMatch {
  user_id: string;
  email: string;
  name: string;
  source: string;
  active: boolean;
  kind: ImportMatchKindValue;
}

/** One row of POST /ldap/directory-users/import/preview. */
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
  /** Per-person conflict decisions; omitted = create-or-link, existing accounts untouched. */
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

export interface UserSyncResult {
  provisioned: number;
  updated: number;
  deactivated: number;
  errors: string[];
}

export interface GroupSyncResult {
  groups: number;
  added: number;
  removed: number;
  errors: string[];
}

/** One directory_sync_state row; `last_result` is the run summary. */
export interface DirectorySyncState {
  kind: string;
  last_run_at: string;
  last_result: Record<string, unknown>;
}

export interface DirectorySyncStatus {
  user_sync: DirectorySyncState | null;
  group_sync: DirectorySyncState | null;
}

export const SEARCH_DEBOUNCE_MS = 150;
