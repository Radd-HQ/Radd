# Spec 40 — SSO: OIDC sign-in with group→role sync

The adoption gate (PLAN §8 #1). The `sso` module implements a standard OIDC
authorization-code + PKCE relying party:

- **`GET /auth/oidc/login`** — discovers the issuer (`RADD_OIDC_ISSUER`), parks
  state/nonce/PKCE-verifier in a short-lived HttpOnly cookie, redirects to the
  provider. **`GET /auth/oidc/callback`** — state check, code exchange
  (client secret + verifier), **id_token verified against the issuer's JWKS**
  (PyJWT/cryptography; iss/aud/exp/nonce all checked), then provisioning and a
  normal `radd_session` cookie.
- **Provisioning**: find-or-create by email claim; created users have
  `password_hash NULL` — the SSO-only marker the auth model reserved on day one.
  `RADD_OIDC_AUTO_PROVISION=false` restricts sign-in to existing accounts.
  Deactivated users are refused.
- **Group→role sync on every login**: the `RADD_OIDC_GROUP_CLAIM` (default
  `groups`) is matched against `RADD_OIDC_ADMIN_GROUPS` → workspace **admin** of
  the default workspace (`RADD_OIDC_DEFAULT_WORKSPACE_SLUG`), else **member**;
  membership is created or its role updated each login. Emits `sso.login` (audit).
- **Login page**: an unauthenticated `GET /instance/login-options` exposes
  `sso_enabled`; the login form shows "Sign in with SSO" when configured.
- Verified end-to-end against a scripted OIDC IdP (discovery/authorize/token/JWKS
  with real RS256 signatures): user provisioned SSO-only, `td-leads` group →
  workspace admin, session works.

## Known simplifications

- OIDC only — **LDAP/AD bind is future** (needs a directory to develop against;
  most studio IdPs — Google Workspace, Keycloak, Authentik, Azure AD — speak OIDC).
- One provider, env-configured; single default workspace for membership sync;
  admin-or-member mapping only (no group→custom-project-role matrix yet).
- Discovery/JWKS cached for the process lifetime (restart after IdP key rotation
  or add cache TTL when it matters).
- No RP-initiated logout (Radd logout clears the local session only).
