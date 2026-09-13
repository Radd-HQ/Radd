/** Auth, profile, users + admin, and personal access tokens (specs 01/34/48/84/86/89). */
import type { PermissionValue } from "./permissions";
import type { InstanceRoleValue } from "./settings";
/** GET /auth/me (spec 01). Spec 86 stage 3: flat shape — `global_role` plus the
 * caller's GLOBAL permission union top-level (the synthetic `workspaces` array
 * is gone). */
export interface Me {
  /** Spec 121: the request carried no credential — this is the Anyone
   *  principal's payload, not a person's. */
  anonymous?: boolean;
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
  /** RADD-836 U1: set while an admin previews this account read-only — the
   * rest of the payload describes the TARGET, which is the point. */
  view_as?: { real_id: string; real_name: string } | null;
  /** RADD-843: server-answered area-visibility facts for the shell nav.
   * RADD-892 made it an open map keyed by the contributing plugin, so a key is
   * absent whenever that plugin is not loaded — and absent (like an older
   * payload) means visible: hiding is presentation. */
  nav?: { timesheet?: boolean; portal?: boolean };
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
  /** Unused single-use recovery codes left (RADD-677). */
  recovery_codes_remaining: number;
}

/** POST /auth/totp/confirm and /auth/totp/recovery-codes — shown ONCE. */
export interface TotpRecoveryCodes {
  recovery_codes: string[];
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
  /** RADD-1009: plain text, "" when never described. */
  description: string;
  created_at: string;
  /** The CURRENT user's effective permissions in this project (spec 06). */
  permissions: PermissionValue[];
  /** RADD-1041 — why this row appears in a `GET /projects` listing: "entitled"
   * (held by grant) or "related" (their own work made it visible, e.g. a
   * ticket they filed). `null` on `POST /projects`'s response. Presentation
   * only — never used to decide access, only to decide what the sidebar's
   * "related projects" preference hides from the rail. */
  via?: "entitled" | "related" | null;
  /** Spec 121: the Public role is granted to Anyone on this project — its
   * public issues are readable without signing in. Derived from the grant. */
  public?: boolean;
  /** Spec 121: the Contributor role is granted to Signed-in users here. */
  contributions?: boolean;
}

/** PATCH /projects/{id} (RADD-1009). Omitted = unchanged. The KEY is not
 *  editable — item keys derive from it — so it is not a field here. */
export interface ProjectUpdate {
  name?: string;
  description?: string;
}

/** PUT /projects/{id}/public-access (spec 121). */
export interface PublicAccessUpdate {
  public: boolean;
  contributions: boolean;
}

/** Aggregate visible-project authority, independent of a directory page. */
export interface ProjectSummary {
  total: number;
  related_count: number;
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
  service: "service",
  email: "email",
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

/**
 * One person as the member-floor directory returns them (RADD-769) —
 * `GET /users/directory`.
 *
 * Everything that only needs to NAME somebody reads this: assignee and reporter
 * pickers, `@`-mention autocomplete, "edited by" bylines. It is deliberately not
 * a `User`: no email, no instance role, no source. Those are administrative
 * facts, they are why `GET /users` is gated on `user.manage`, and requiring that
 * atom to draw an assignee dropdown is what put a 403 toast on nearly every
 * issue and page an ordinary member opened.
 */
export interface UserSummary {
  id: string;
  name: string;
  active: boolean;
  /** Auth backend (`local`/`ldap`/`oidc`/`service`) — pickers badge `service`
   * rows so an automation identity is never mistaken for a colleague (RADD-869). */
  source: string;
  avatar_color?: string | null;
  avatar_emoji?: string | null;
  /** RADD-938 — only when the row was fetched with a `project_id`: does this
   *  person hold item.read on THAT project through a grant? `undefined`/`null`
   *  means the question was not asked, which must not render as a warning. */
  has_access?: boolean | null;
  /** RADD-1034 — true when this row is a `UserSource.EMAIL` account (a mail-in
   *  requester), returned only from a directory fetch with
   *  `include_requesters: "true"`. Absent/false everywhere else, since the
   *  directory excludes those accounts by default. */
  external?: boolean;
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
/** RADD-784: one scope where a successor candidate holds less than the account
 * being deleted. Access never transfers on delete, so the candidate must
 * already hold at least what the account holds. */
export interface SuccessorGap {
  scope_type: "instance" | "global" | "project" | "space";
  label: string;
  scope_id: string | null;
  missing: string[];
}

export interface SuccessorCheck {
  viable: boolean;
  gaps: SuccessorGap[];
}

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
  /** Spec 113: raw atoms narrowing the key below its account; null = unscoped. */
  scopes: TokenScopes | null;
}

export interface ApiTokenCreate {
  name: string;
  expires_at?: string | null;
  /** RADD-1009: the browser can finally narrow a personal key (spec 113 shape). */
  scopes?: TokenScopes | null;
}

/** POST /tokens response — `token` is shown exactly once. */
export interface ApiTokenCreated {
  token: string;
  id: string;
  name: string;
  prefix_display: string;
  expires_at: string | null;
  scopes: TokenScopes | null;
}

/** Service accounts + scoped keys (spec 113). */
export type ServiceAccount = {
  id: string;
  email: string;
  name: string;
  active: boolean;
  created_at: string;
  token_count: number;
};

/** Raw permission atoms, per scope. `null` on a key means unscoped. */
export type TokenScopes = {
  global?: string[];
  projects?: Record<string, string[]>;
};

export type ServiceAccountKey = {
  id: string;
  name: string;
  prefix_display: string;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
  scopes: TokenScopes | null;
};

export type ServiceAccountKeyCreated = ServiceAccountKey & { token: string };
