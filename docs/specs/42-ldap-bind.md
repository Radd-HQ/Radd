# Spec 42 — LDAP/AD bind: directory sign-in

The directory half of SSO (PLAN §8 #1; OIDC shipped in spec 40). The `ldap`
module implements **direct bind** — the pattern proven in production by
pipe-status: the user's own credentials authenticate the LDAP connection, so
**no service/bind account is ever stored**.

- **`POST /auth/ldap/login`** `{username, password}` — binds to `RADD_LDAP_URL`
  (e.g. `ldaps://ad.example.com:636`) as the UPN
  `<username>@<RADD_LDAP_USER_DOMAIN>`. A rejected bind (or a username failing
  the `[a-zA-Z0-9._-]{1,64}` shape check) is a uniform 401. The blocking
  `ldap3` round-trip runs in a worker thread (`asyncio.to_thread`), so the
  event loop never stalls on a slow directory.
- **On that same connection** (the user can read their own entry): email
  (`RADD_LDAP_EMAIL_ATTRIBUTE`, default `mail`; falls back to the UPN) and
  display name (`RADD_LDAP_NAME_ATTRIBUTE`, default `displayName`; falls back
  to the username) are read, and admin-group membership is checked with AD's
  **transitive matching rule** (`memberOf:1.2.840.113556.1.4.1941:=`) so
  **nested** membership counts — plain `memberOf` only lists direct groups.
  `RADD_LDAP_ADMIN_GROUPS` is a comma-separated list of group **CNs**; each is
  resolved to its DN first. All filter values pass through
  `escape_filter_chars` (no filter injection).
- **Search base**: `RADD_LDAP_BASE_DN`, or derived from the user domain
  (`ad.example.com` → `DC=ad,DC=example,DC=com`).
- **Provisioning + role sync** exactly as OIDC (spec 40): find-or-create by
  email with `password_hash NULL` (the SSO-only marker), deactivated users
  refused, `RADD_LDAP_AUTO_PROVISION=false` restricts to existing accounts;
  default-workspace (`RADD_LDAP_DEFAULT_WORKSPACE_SLUG`) membership created or
  role-synced admin/member on every login — via the shared
  `auth.service.sync_workspace_membership` seam (extracted from spec 40's
  inline block; `sso` now calls it too). Emits `ldap.login`, then an ordinary
  `radd_session` cookie is issued.
- **Login page**: `GET /instance/login-options` grows `ldap_enabled`; when set,
  the login form offers an **Email / Directory** toggle — directory mode is a
  username + password form posting to `/auth/ldap/login`.
- Config: `RADD_LDAP_*` in `config.py`; empty `RADD_LDAP_URL` = module dormant
  (endpoint 403s). `ldap_timeout_seconds` bounds connect/receive waits.

## Verification

- Pure core under pytest (`tests/test_ldap.py`): base-DN derivation, username
  shape check, entry→user mapping incl. UPN/username fallbacks, filter
  construction with hostile input escaped.
- Full login flow (bind → provision → membership sync → session cookie)
  exercised in-process via ASGI with a stubbed `_bind_and_lookup`, against a
  real database: SSO-only user created, admin group → workspace admin,
  role re-synced on a later login, cookie works against `/auth/me`.

## Known simplifications

- The wire bind is line-for-line the production pipe-status pattern but is not
  exercised against a real AD in CI (no directory to develop against — same
  gate spec 40 noted; first real-AD login is the deploy-time check).
- AD-flavored: UPN bind + `sAMAccountName` + the AD-only transitive matching
  rule. Plain-OpenLDAP shops (DN templates, no nested-group rule) would need a
  strategy toggle — not built until someone needs it.
- One directory, env-configured; single default workspace; admin-or-member
  mapping only (mirrors spec 40's scope).
- No connection pooling — one short-lived connection per login, which is the
  security point of direct bind (nothing to pool) and trivially fine at studio
  login rates.
