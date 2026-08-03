/** One role a new account receives, at one scope (RADD-780). `project_id`
 *  null = instance-wide, exactly as in a role grant. */
/**
 * One "who gets what" rule on a provider (RADD-782).
 *
 * EMPTY `domains` matches every address — the catch-all. Every rule whose
 * domains match is applied, so a catch-all and a domain rule compose by union
 * rather than racing.
 */
export interface SsoProvisioningRule {
  name: string;
  domains: string[];
  grants: SsoDefaultGrant[];
  team_ids: string[];
}

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
  /** What a NEW account gets, per matching rule (RADD-782). Applied ONCE at
   *  account creation and never re-applied, so an admin's later change to that
   *  person's access is never undone. */
  provisioning_rules: SsoProvisioningRule[];
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
  provisioning_rules?: SsoProvisioningRule[];
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
