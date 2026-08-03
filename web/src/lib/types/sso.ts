/** One role a new account receives, at one scope (RADD-780). `project_id`
 *  null = instance-wide, exactly as in a role grant. */
export interface SsoDefaultGrant {
  role_id: string;
  project_id: string | null;
}

/** SSO provider registry (spec 110): providers, signup policy, login buttons. */

/** Which IdP a provider talks to. Every kind runs the same OIDC code+PKCE flow. */
export const SsoKind = {
  google: "google",
  oidc: "oidc",
} as const;
export type SsoKindValue = (typeof SsoKind)[keyof typeof SsoKind];

/** Explicit opt-out of the signup allowlist (mirrors the server's WILDCARD_DOMAIN). */
export const SIGNUP_DOMAIN_WILDCARD = "*";

/** One provider row from GET /sso/providers — the client secret never leaves the server. */
export interface SsoProviderRead {
  id: string;
  name: string;
  kind: SsoKindValue;
  enabled: boolean;
  position: number;
  /** "" = the kind's default (Google's issuer is pinned server-side). */
  issuer: string;
  client_id: string;
  has_client_secret: boolean;
  scopes: string;
  auto_provision: boolean;
  /** Bare lowercase domains allowed to CREATE an account. EMPTY = no signups. */
  allowed_signup_domains: string[];
  require_verified_email: boolean;
  group_claim: string;
  admin_groups: string;
  /** What a NEW account gets from this provider (RADD-780/781) — any number of
   *  roles, each global or scoped to a project, plus teams to join. Applied
   *  ONCE, at account creation, and never re-applied, so an admin's later
   *  change to that person's access is never undone. */
  default_grants: SsoDefaultGrant[];
  default_team_ids: string[];
  source: string;
  /** False when the row can't complete a flow yet — explains its absence from login. */
  configured: boolean;
  /** What to paste into the IdP's console. */
  redirect_uri: string;
}

/** POST /sso/providers body; PATCH sends a partial ("" client_secret = keep stored). */
export interface SsoProviderPayload {
  name?: string;
  kind?: SsoKindValue;
  enabled?: boolean;
  position?: number;
  issuer?: string;
  client_id?: string;
  client_secret?: string;
  scopes?: string;
  auto_provision?: boolean;
  allowed_signup_domains?: string[];
  require_verified_email?: boolean;
  group_claim?: string;
  admin_groups?: string;
  default_grants?: SsoDefaultGrant[];
  default_team_ids?: string[];
}

/** GET /sso/kinds — what the "add a provider" form prefills itself with. */
export interface SsoKindInfo {
  kind: SsoKindValue;
  name: string;
  issuer: string;
  scopes: string;
}

/** GET /auth/sso/providers (unauthenticated) — enough to draw a login button. */
export interface SsoProviderPublic {
  id: string;
  name: string;
  kind: SsoKindValue;
}

/** POST /sso/providers/{id}/test — failures come back as data, never a 502. */
export interface SsoProbeResult {
  ok: boolean;
  error: string;
  authorization_endpoint: string;
}
