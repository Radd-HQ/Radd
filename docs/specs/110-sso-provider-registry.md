# Spec 110 — Sign in with Google: the SSO provider registry

User ask: enable Sign in with Google, but with **signups disabled except for
named domains** (`hjarrar.com`, `radd-hq.com`, `acme.example`, editable), and a
first-time Google login must **join the existing AD account** for that person
rather than creating a duplicate.

Google is an OIDC provider, so the spec-40 `sso` module already did the hard
part — authorization code + PKCE, JWKS-verified `id_token`. Three gaps stood
between that and the ask, and the third was a bug.

## 1. Providers are rows, not the environment

`settings.oidc_*` could name exactly ONE issuer and needed a redeploy to
change, so Google could not coexist with a corporate IdP — and the domain
allowlist has to be editable at runtime, since "let this domain in" is an
everyday admin act, not a deploy. Same move specs 101/102 made for AI providers
and storage hosts.

`sso_providers`: `kind` (`google` | `oidc`), name (the button's label),
enabled, position, issuer, client id/secret, scopes, `auto_provision`,
`allowed_signup_domains` (JSONB), `require_verified_email`, `group_claim`,
`admin_groups`, `source`. `KIND_DEFAULTS` supplies discovery per kind — Google's
issuer is pinned, so an admin pastes a client id/secret and a domain list and
nothing else. Every kind runs the SAME engine; a kind never forks the flow.

**Spec 121 restatement (RADD-1145).** "A kind only supplies discovery defaults"
was true while every kind was OIDC. GitHub is plain OAuth2 — no discovery
document, no `id_token` — so the rule is now: **a kind supplies its ENDPOINTS
and its PROFILE STRATEGY; the state + PKCE + one-callback + identity-pinning +
signup-allowlist engine is shared.** `KindDefaults` (`types.py`) declares both
per kind — `discovery` (fetch `/.well-known/openid-configuration` vs. pinned
endpoints) and `profile` (`id_token` verified against the JWKS vs. a profile
API called with the access token) — and `idp.py` is the only code that reads
them: `metadata()` returns a synthetic document for a pinned kind, `profile()`
turns either token response into the SAME claim-shaped dict, so `provision()`
never learns which kind signed the person in. GitHub's subject is the numeric
`id` (never `login`, which is renameable); its email is the `primary` +
`verified` entry from `/user/emails`, emitted as `email_verified`, so
`require_verified_email` and the email-once linking rule apply untouched.

The env `oidc_*` settings survive as **seed-only** input (`seed_from_env`, runs
only on an empty table, exactly the `ai/registry.py` rule) plus a new
`RADD_OIDC_SIGNUP_DOMAINS`. An empty list + `auto_provision` on seeds the `"*"`
wildcard, preserving spec 40's anyone-at-the-IdP behavior for a deployment
already relying on it.

Caches (discovery document, JWKS client) are keyed **per provider** — a single
module-level cache would have served Google's metadata for Okta's flow. Admin
writes invalidate the edited row's cache, so a changed issuer needs no restart.

## 2. Identity is pinned to the subject; email is used ONCE

`user_identities` (provider_id, subject) → user, unique on (provider, subject).

- **First** login: match the existing account by email, and only when the IdP
  says it verified that address. This is what lands a Google login on the
  person's AD account. The account keeps its `source`, role and history — the
  login just becomes another door into it.
- **Every later** login: match on the IdP's immutable `sub`, ignoring email
  entirely. A mailbox rename in AD no longer forks the account, and a recycled
  address cannot inherit a leaver's.

`require_verified_email` defaults ON and is the security hinge: linking by email
is precisely what an unverified address would exploit, so an IdP that lets a
user self-assert `email` could otherwise hand out other people's accounts. The
per-provider opt-out exists for an issuer that omits the standard claim, and
names what it gives up.

## 3. The role-clobber bug

Spec 40 wrote `user.instance_role` on every login unconditionally. Google ships
no group claim, so the moment it linked to an AD-provisioned **admin**, that
login **demoted them to member** — and every login after. Now a provider with
no `admin_groups` configured carries no role opinion and leaves `instance_role`
alone; configure admin groups and spec 40's in⇒admin / out⇒member sync returns.

## Signup policy

`signup_allowed(provider, email)`: `auto_provision` off ⇒ no. `"*"` in the list
⇒ yes. Otherwise the email's domain must be in the list. **Empty list = no
signups**, the strict reading of the ask, so a provider added without a list
can't quietly let the internet in. The list gates **creation only** — an
existing account signs in from any domain, so a contractor already on the
instance is never locked out. Domains are normalized on write (`@Radd-HQ.com`,
`hussein@HJarrar.com` and ` acme.example ` all store as bare lowercase): a list
that silently doesn't match is a support ticket.

## API

- `GET /auth/sso/providers` — UNAUTHENTICATED, the login page's buttons. Only
  enabled + fully-configured rows, and only id/name/kind: never a client id,
  issuer or policy. It is its own endpoint rather than a flag on
  `/instance/login-options` because a button needs an id and a label, and a
  boolean can only describe the single-provider world spec 40 lived in.
- `GET /auth/oidc/login?provider_id=` — no id resolves to the only configured
  provider, keeping single-IdP instances and spec 40's bare link working.
- `GET /auth/oidc/callback` — one callback for every provider (the flow cookie
  carries which), so adding a provider needs no new registration on our side.
  **Refusals REDIRECT to `/login?sso_error=…` rather than returning 403 JSON**:
  this leg runs in a browser address bar, so the JSON body would be the page a
  person sees, and "you can't sign up from this domain" is a message they have
  to read and act on.
- `/sso/providers` CRUD + `/sso/kinds` + `/sso/providers/{id}/test` (fetches the
  issuer's discovery document — the only thing checkable without a human
  completing a login; failures come back as DATA, never a 502), instance-admin.

The `sso` capability now reads a process-local snapshot refreshed on write and
at startup, because a `CapabilitySpec` check is sync and cannot open a session
(the spec 101/102 precedent).

## SPA

- **Settings → Sign-in** (`KeyRound`, Server group, admin): provider table with
  a status chip (On login page / Disabled / **Incomplete**, so a row missing
  credentials explains its own absence), the domain allowlist as chips, and a
  Roles column reading "Left alone" vs "Synced from `<claim>`". The dialog
  carries the copyable **redirect URI** to paste into the IdP console; the
  allowlist is a `TokenMultiSelect` whose help line states the live consequence
  ("Empty means NO new accounts…" / "`*` lets anyone…").
- **Login page**: one button per provider with Google's four-colour G (fixed
  brand colours — they must not theme-invert), plus the `sso_error` banner.

## Merge/delete

`user_identities.user_id` joins `_MERGE_REPOINT` — federated logins follow the
person, and CASCADE would otherwise have destroyed the source's identities. NOT
in `_MERGE_DEDUPE`: uniqueness is (provider, subject), so a survivor holding two
identities from one provider is legal and correct.

## Tests

`server/tests/test_sso_providers.py` (22): allowlist gating incl. empty/wildcard/
auto-provision-off, existing-account-from-unlisted-domain, domain normalization,
**AD linking**, **the role-clobber regression**, group sync when configured,
subject pinning across a rename, recycled-address isolation, unverified-email
refusal (creation AND takeover), `"true"`-as-string, registry mechanics.

Migration `d110ssoprov`. Rendered proof (CDP): login button + refusal banner +
settings page + dialog measured; the dialog needed `wide` because only the
wide/extraWide Modal panels carry `max-h-full overflow-y-auto` and the form is
taller than a 900px viewport — Save was below the fold and unreachable.
