# Spec 113 — service accounts, and keys that carry less authority than the person who made them

**.** Every API token today is a personal one: it acts as its owner, with all of
its owner's authority, and revoking it means touching a human's account. Agents,
integrations and automations need identities of their own — and keys that are
narrower than the identity behind them.

## Why

Three problems, one root.

- **Attribution.** A script running on someone's PAT files issues as that
  person. The audit log is then wrong in a way nobody can reconstruct later.
- **Blast radius.** A token minted by an admin IS an admin, everywhere, forever.
  There is no way to hand out "can read RADD and comment" without creating a
  whole user and hoping nobody grants it more.
- **The MCP catalog cannot be honest** (spec 114) without a machine-readable
  answer to "what may this key do". The permission engine can already answer it
  for an actor; it has nothing to intersect with for a key.

The automation SYSTEM actor already showed the shape: a `User` row with a pinned
UUID that nobody logs in as. Every FK in the system points at `users` —
assignee, reporter, comment author, worklog author, `events.actor_id` — so a
service account that is not a user row would need a parallel path through all of
them. It is a user. It just cannot log in.

## What

- **`UserSource.SERVICE`.** A service account is a user with `source=service`,
  a synthetic email (`<slug>@service.radd.local`), no password hash, and no
  identity rows. Interactive login refuses it — local, LDAP and SSO alike — with
  "service accounts authenticate with an API key". It stays a first-class
  principal everywhere else: assignable, mentionable, visible in the audit log,
  deactivatable, and deletable through the spec-89 reassignment path.
- **Admin CRUD** under `/service-accounts`, gated on new atoms
  `service_account.create` / `.update` / `.delete` (implied by `global.manage`),
  contributed via one `CRUD_RESOURCES` line. Settings → Service accounts lists
  each account, its grants, its keys, and each key's last use.
- **Grants are the existing ones.** A service account gets a global role grant
  (spec 87) and/or project member grants, exactly as a person does. Nothing new:
  the account's authority is resolved by the engine that already exists. This is
  the account's **ceiling**.
- **`api_tokens.scopes`** — a JSONB narrowing, expressed in **raw permission
  atoms**, the same vocabulary the roles matrix uses:

  ```json
  {"global": ["item.read", "doc.read"],
   "projects": {"<project_id>": ["item.create", "item.update", "comment.write"]}}
  ```

  `NULL` means unscoped — the key carries the account's full authority, which is
  exactly what every personal PAT does today, so nothing existing changes
  behaviour.
- **Enforcement is an intersection, at one seam.** The authenticated principal
  now carries an optional capability filter (the token's scopes). `authz.resolve`
  applies it after the actor's permissions are resolved: `effective = resolved ∩
  scope`. A key can therefore never exceed its account, and an account demoted
  tomorrow narrows every key it holds, immediately. Because it lands in the
  resolver rather than in each router, it covers the REST API, the MCP endpoint,
  automations invoked over the API, and any future surface for free.
- **A scope editor** on key creation: atoms grouped by resource with a
  project selector, defaulting to the account's own grants so the common case is
  "same as the account, minus the dangerous parts". The raw value is shown and
  editable — a scope is data, not a wizard.
- **Key lifecycle**: expiry (existing column, now surfaced), `last_used_at`,
  revoke, and rotation as create-then-revoke. The raw key is shown once.
- **A seeded `Agent` account** for this repository's assistant, with a key
  scoped to the RADD project — the first consumer, and the reason to check the
  intersection is real.

## Invariants tested

- **A key cannot exceed its account.** A scope granting `global.manage` on an
  account holding only `item.read` resolves to `item.read`.
- A scoped key is refused a permission its scope omits even when the account
  holds it — checked on a project-scoped atom and a global one.
- Revoking the account's grant narrows the key with no key edit.
- An unscoped token behaves exactly as before (the personal-PAT path is
  unchanged, pinned by the existing token tests).
- Interactive login as a service account is refused on every auth path; API-key
  auth succeeds.
- Deleting a service account revokes its keys and reassigns its authored work
  (spec 89), rather than orphaning either.
- Scopes round-trip through the API unchanged, and an unknown atom is a 422 at
  write time rather than a silent no-op at check time.

## Known simplifications

- No per-key IP allowlist, and no OAuth client-credentials flow. The key is a
  bearer token, as today.
- No presets in the scope editor. Atoms are the vocabulary; a preset library can
  come later, and would be the same shape as the card-layout presets (spec 109).
- A service account has no separate quota or rate limit.
- Scope changes take effect on the next request; there is no token
  re-issuance or push invalidation, because the check is a live resolve.
