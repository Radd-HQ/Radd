/** Auth, profile, users + admin, and personal access tokens (specs 01/34/48/84/86/89). */
import type { PermissionValue } from "./permissions";
import type { InstanceRoleValue } from "./settings";
/** GET /auth/me (spec 01). Spec 86 stage 3: flat shape — `global_role` plus the
 * caller's GLOBAL permission union top-level (the synthetic `workspaces` array
 * is gone). */
export interface Me {
  id: string;
  email: string;
  name: string;
  instance_role: InstanceRoleValue;
  global_role: InstanceRoleValue;
  permissions: PermissionValue[];
  /** Spec 87: owns or manages at least one team. Per-team delegation doesn't
   * show up in `permissions`, so this is what gates the Teams settings nav. */
  manages_teams?: boolean;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
  timezone?: string;
}

/** PATCH /auth/me (spec 34) — omitted keys unchanged; explicit null clears avatar. */
export interface ProfileUpdate {
  name?: string;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
  timezone?: string;
}

/** POST /auth/login body (spec 01). */
export interface LoginRequest {
  email: string;
  password: string;
}

/** POST /auth/login/totp (spec 48) — password re-verified along with the code. */
export interface TotpLoginRequest extends LoginRequest {
  code: string;
}

/** GET /auth/totp (spec 48). */
export interface TotpStatus {
  enabled: boolean;
  /** Setup created but not yet confirmed with a code. */
  pending: boolean;
}

/** POST /auth/totp/setup (spec 48) — paste into an authenticator app. */
export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
}

export interface Project {
  id: string;
  key: string;
  name: string;
  created_at: string;
  /** The CURRENT user's effective permissions in this project (spec 06). */
  permissions: PermissionValue[];
}

export interface ProjectCreate {
  key: string;
  name: string;
}

/** Which auth system created an account (spec 84, mirror of `UserSource`). */
export const UserSource = {
  local: "local",
  ldap: "ldap",
  oidc: "oidc",
  unknown: "unknown",
} as const;
export type UserSourceValue = (typeof UserSource)[keyof typeof UserSource];

/** GET /users (spec 01; source/last-login — spec 84). */
export interface User {
  id: string;
  email: string;
  name: string;
  instance_role: InstanceRoleValue;
  active: boolean;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
  timezone?: string;
  source: UserSourceValue;
  last_login_at: string | null;
}

/** POST /users (spec 01). */
export interface UserCreate {
  email: string;
  name: string;
  password: string;
  instance_role?: InstanceRoleValue;
}

/** PATCH /users/{id} (spec 84, instance admin) — omitted keys unchanged.
 * `instance_role` is THE role ladder (spec 86): admin|member, server-wide. */
export interface UserAdminUpdate {
  name?: string;
  active?: boolean;
  instance_role?: InstanceRoleValue;
}

/** POST /users/{id}/merge — fold the path user (the duplicate) into this one. */
export interface UserMergeRequest {
  into_user_id: string;
}

/** One candidate group from GET /users/duplicates (spec 84). */
export const DuplicateKind = {
  emailLocalPart: "email_local_part",
  name: "name",
} as const;
export type DuplicateKindValue = (typeof DuplicateKind)[keyof typeof DuplicateKind];

export interface DuplicateUserGroup {
  kind: DuplicateKindValue;
  key: string;
  users: User[];
}

/** GET /users/{id}/content (spec 89) — what a delete would hand over. Everything
 * here moves to the successor EXCEPT worklogs, which are destroyed so nobody is
 * credited with hours they didn't work. */
export interface UserContentSummary {
  reported_items: number;
  assigned_items: number;
  comments: number;
  documents: number;
  views: number;
  dashboards: number;
  owned_teams: number;
  attachments: number;
  approvals: number;
  worklogs: number;
  worklog_seconds: number;
}
// ---------------------------------------------------------------------------
// Personal access tokens (spec 01)
// ---------------------------------------------------------------------------

export interface ApiToken {
  id: string;
  name: string;
  prefix_display: string;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiTokenCreate {
  name: string;
  expires_at?: string | null;
}

/** POST /tokens response — `token` is shown exactly once. */
export interface ApiTokenCreated {
  token: string;
  id: string;
  name: string;
  prefix_display: string;
  expires_at: string | null;
}
