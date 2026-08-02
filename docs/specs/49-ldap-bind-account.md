# Spec 49 — LDAP bind-account mode + bulk AD user import

Interactive login stays **direct bind** (spec 42) — no stored account. This
adds an *optional, separate* **service-account** path used for **one thing
only**: enumerating the directory to bulk-provision users ahead of their first
login.

## Config (all empty = disabled)

- `RADD_LDAP_BIND_DN` / `RADD_LDAP_BIND_PASSWORD` — the read-only service
  account. Empty `BIND_DN` = enumeration off (`bind_account_enabled()` false).
- `RADD_LDAP_USER_SEARCH_BASE` — search root ("" = the derived base DN; narrow
  to an OU to scope the import).
- `RADD_LDAP_USER_FILTER` — default `(&(objectCategory=person)(objectClass=user)(mail=*))`.
- `RADD_LDAP_PAGE_SIZE` — AD caps a single search at ~1000 rows; the search
  pages through (`paged_search`).

## Service (`ldap/service.py`)

- `search_directory_users()` — binds with the service account, pages the
  directory under `user_search_base()`, reads `sAMAccountName` + the configured
  mail/name attributes, returns `DirectoryUser`s. **Entries without a real
  `mail` are skipped** (no synthesized UPNs for bulk import), deduped by email.
  `is_admin` is left False — a user's real role syncs on their first
  interactive direct-bind login (spec 40/42 path), so enumeration stays cheap
  and never needs the transitive group check per user.
- Pure helpers unit-tested: `bind_account_enabled()`, `user_search_base()`,
  `_entry_to_directory_user()` (email/username requirements + fallbacks).

## Script (`scripts/import_ad_users.py`)

`uv run python scripts/import_ad_users.py --email … --password … [--dry-run]`
with `RADD_LDAP_*` in the environment. Binds + enumerates, then creates each
user via the Radd REST API (`POST /users`, `instance_role=member`, a **random**
password — these accounts authenticate via AD, matched **by email**, so a later
direct-bind login links up and syncs the role). `--dry-run` enumerates and
prints without creating (and needs no Radd credentials). The **service
password is read from the environment only**, never a CLI flag.

## Why not an in-app endpoint

Bulk directory enumeration is an operator action (needs the service secret in
the environment, runs once at rollout), not a request served to end users — so
it lives in a script alongside `import_jira.py`, not behind an HTTP route.

## Verification

- Pure: gate + search-base defaulting + entry mapping (skips email-less /
  username-less entries) — `tests/test_ldap.py`.
- Flow: the script's enumerate→provision path exercised with the wire
  enumeration stubbed — dry-run lists users; a real run creates them in the live
  instance (verified present, then removed).
- The actual `ldap3` service-account bind + `paged_search` runs against real AD
  at rollout (needs the service credential; no directory in CI — the same gate
  spec 40/42 noted).

## Known simplifications

- Enumerated users are provisioned as **member**; real roles sync on first
  login (no bulk group→role mapping pass).
- No incremental sync / de-provisioning (a rollout tool, not a scheduled
  reconciler); re-running is idempotent (existing emails 409 → skipped).
- One service account, one search base.
