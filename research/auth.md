# Auth/AuthZ research: self-hosted issue tracker (single org, VFX studio w/ AD)

Research date:

## 1. Build vs delegate

Every reference app (Grafana, GitLab CE, Mattermost, OpenProject) **embeds auth natively** — none requires an external IdP — and every one paywalls part of it:

| App | LDAP auth | OIDC/OAuth | LDAP group sync | PATs / service accounts |
|---|---|---|---|---|
| Grafana (Go) | Free | Free (generic OAuth) | **Enterprise-only** (Team Sync + active LDAP sync); SAML Enterprise | API keys removed 2025 → **service accounts + tokens** |
| GitLab CE (Rails) | Free | Free (OmniAuth) | **EE-only** | PATs free, `glpat-` prefix, project/group tokens (bot users), scopes, expiry, rotation API |
| Mattermost (Go) | **Paid** | **Paid** (SSO removed from free tier 2025) | Paid | PATs + bot accounts free |
| OpenProject (Rails) | LDAP auth free | **Enterprise** (both OIDC and SAML) | **Enterprise** | Single per-user API key (weak model) |

**Shipping LDAP + OIDC + group sync free is a differentiator precisely because everyone else paywalls part of it.**

Dedicated IdPs: Keycloak = best AD federation, heaviest ops (Java, 2GB RAM, migration treadmill). Authentik = community favorite for lower-ops (Python/Django, can act as OIDC IdP + LDAP server simultaneously; some enterprise-gated features). Zitadel = weak LDAP (login only, no sync) — wrong for AD shops. Dex = stateless OIDC shim with LDAP connector, "lightweight enough to bundle" — excellent as an optional AD-to-OIDC adapter. Ory = overkill for single-org internal.

**Recommendation:** embed auth natively; never require an IdP. Design the OIDC client generically so Keycloak/Authentik/Entra/Google plug in with three config lines. Document a reference compose with Dex/Authentik for orgs wanting MFA/WebAuthn at the IdP.

## 2. Recommended pattern: dual OIDC + direct LDAP

1. **Native OIDC RP** (authorization code + PKCE) against any discovery-capable provider.
2. **Native direct LDAP bind**: search-bind flow (service account binds → finds user DN by `sAMAccountName`/`userPrincipalName` → re-bind as user). LDAPS + StartTLS; AD nested groups via `LDAP_MATCHING_RULE_IN_CHAIN` (`1.2.840.113556.1.4.1941`).
3. **Local password accounts** (argon2id) as break-glass admin — never make the directory the only way in.

- **JIT provisioning** on first LDAP/OIDC login, configurable default role.
- **Identities table** (`user_id, provider, external_uid`), keyed on OIDC `iss`+`sub` and LDAP `objectGUID` — **never email or DN alone**. Config-gated email auto-linking (`auto_link_by_email`, default on for single-org).
- **Group → role mapping**: admin-configured rules mapping LDAP groups / OIDC `groups` claims to instance and per-project roles. Sync at login + hourly background job that **disables (never deletes)** users removed from the directory. This is exactly what OpenProject/GitLab EE/Grafana Enterprise charge for — ship free.
- **SAML:** skip in v1 (OIDC is the 2026 default; SAML-only IdPs can be bridged via Dex/Keycloak). Keep the provider abstraction open.
- **SCIM:** skip; periodic LDAP sync is the lifecycle mechanism for single-org self-hosted.

## 3. API tokens

- **Format:** `prefix_` + ≥160 bits CSPRNG base62 + CRC32 checksum in last chars (GitHub's design — enables offline validation by secret scanners). Distinct prefixes per token kind (PAT / service-account token / webhook secret).
- **Storage:** store only SHA-256(token) — fast unsalted hash is correct for full-entropy inputs; show once; retain prefix+last4 for display.
- **Scopes:** coarse v1 — `api`, `read_api`, `admin` + optional per-project restriction.
- **Expiry:** default-on (90d, max 366), warning emails, rotation endpoint (GitLab `POST .../rotate` pattern).
- **Last-used tracking:** `last_used_at` (+IP), write-throttled; admin credentials inventory with force-revoke; audit-log every create/revoke.
- **Service accounts:** Grafana post-2025 model — machine identities not tied to a human user; own role/memberships; multiple revocable tokens; disable-able as a unit; exempt from directory-sync deactivation (render-farm hooks and CI must not break when an artist leaves).
- **Webhooks:** Standard Webhooks spec — per-endpoint secret, HMAC-SHA256 over `msg_id.timestamp.raw_body`, verify raw body with constant-time compare, ~5min replay window, secret rotation with dual-signing overlap.

## 4. AuthZ model

**Plain roles table, two levels — no policy engine.**
- Instance: `admin`, `member` (+ configurable default role).
- Project: `admin`, `member`, `viewer`, optional `guest` (sees only own/mentioned issues — the "external client reviews shots" case).
- `project_memberships(user_id | group_id, project_id, role)` — membership via group so LDAP sync maps cleanly. Highest role wins (GitLab semantics).
- Enforce in one place: a small `can(actor, action, resource)` module with unit tests (~200 lines).
- Policy engines (Casbin/Cerbos/OpenFGA) not warranted: no multi-service, no sharing graphs; OpenFGA adds a dual-write tuple-store problem.
- **Per-field / per-issue-type permissions: don't.** Jira's worst operational burden; Linear/GitHub/Shortcut all rejected it. One per-issue `confidential` flag (GitLab model) covers the sensitive cases. Seam the `can()` module so type rules could slot in later.

## 5. Libraries (Python/FastAPI)

- OIDC client: **Authlib** (`authlib.integrations.starlette_client`, discovery + PKCE).
- LDAP: **bonsai** (C-backed, asyncio-native) or **ldap3** (pure-Python, run in threadpool; maintenance slowed).
- Sessions: server-side sessions in Redis/Postgres keyed by CSPRNG cookie ID (e.g. `starsessions`); Starlette's `SessionMiddleware` is client-side signed-cookie only — MVP-only.
- Passwords: **`pwdlib[argon2]`** (Passlib is unmaintained, breaks on Python ≥3.13), argon2id, migrate-on-login.
- TOTP: `pyotp`.

## 6. Production-grade auth checklist

1. Server-side sessions: CSPRNG ID; `HttpOnly; Secure; SameSite=Lax`; `__Host-` prefix; server-side store for revocation.
2. Session lifecycle: rotate ID at login; absolute + idle timeouts; "log out all sessions"; active-session list.
3. CSRF on state-changing browser routes; PAT-authed API exempt.
4. argon2id (OWASP params); migrate-on-login; never log hashes.
5. PATs as SHA-256 digests, shown once, prefixed + checksummed.
6. Token expiry defaults + rotation endpoint + expiry warnings.
7. `last_used_at` (+IP) write-throttled; admin credentials inventory.
8. Service accounts decoupled from humans; exempt from sync deactivation.
9. Rate limiting + lockout on login and token failures (per-account and per-IP); protect the LDAP bind path (DoS vector against AD).
10. Append-only audit log: login success/failure, token lifecycle, role/membership changes, auth-config changes, group-sync actions — actor, IP, UA, timestamp.
11. MFA: delegate to IdP for OIDC; native TOTP + recovery codes for local/LDAP; admin "require MFA" toggle.
12. LDAP hardening: LDAPS/StartTLS with CA verification; low-privilege bind account; escape filter input; **reject empty-password binds explicitly** (anonymous-bind pitfall logs anyone in).
13. Directory sync deactivates, never deletes; abort if >N% of users would be disabled in one run.
14. OIDC hardening: code+PKCE only; validate iss/aud/nonce/exp; strict redirect-URI allowlist; JWKS re-fetch on rollover.
15. Identities keyed on iss+sub / objectGUID; config-gated email linking.
16. Break-glass local admin, MFA-protected, excluded from sync.
17. Standard Webhooks HMAC signing with replay window and secret rotation.
18. Secrets via env/files (OpenBao-friendly); AES-GCM if in DB; never in audit log.
19. HSTS, CSP; trust X-Forwarded-For only from configured proxies.
20. Constant-time comparisons; uniform "invalid credentials" errors (no user enumeration); uniform timing on LDAP not-found vs wrong-password.
