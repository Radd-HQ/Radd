# Spec 88 — AD user import: flag duplicates, overwrite or merge

**Status: shipped.**

User direction: *"When importing AD users, I want to flag duplicate usernames
already in the system and offer to overwrite or merge keeping the AD entry — so
essentially update the users list from AD and merge conflicts, asking whether or
not to overwrite. It should overwrite email and such."*

## The problem

Radd identifies people by **email**, and accounts arrive from several places: the
Jira importer, local signup, OIDC, an older mail domain. `find_or_create_user`
matched on email alone, so importing `jsmith@corp.example` while the same human was
already present as `jsmith@old-domain.example` created a **second account** and split
their history — issues under one identity, comments and worklogs under the other.
The import reported this as `created: true` and moved on.

Note the shape of the ask: Radd has **no username column**. An AD
`sAMAccountName` can therefore only be compared against the *local part* of an
existing email, which is what "duplicate username" resolves to here.

## Two steps

**`POST /ldap/directory-users/import/preview`** — a dry run. `plan_user_import`
(pure, in `ldap/userimport.py`) classifies every selected directory user against
the existing roster:

| status | meaning |
|---|---|
| `new` | nothing matches — a plain create |
| `linked` | the exact email is already here; the import refreshes it |
| `conflict` | looks like an existing person under a **different** email |

Matches carry *why* they matched (`ImportMatchKind`): `email` (exact — certainly
the same account), `username` (the AD username, or the local part of the AD
address, equals an existing email's local part), or `name` (identical display
name). An account is reported once, under its strongest match.

**`POST /ldap/directory-users/import`** — now accepts a `resolution` per entry.
Both write verbs end with the directory as the source of truth; they differ in
how many Radd accounts are involved:

- **`overwrite`** — one account. Its email and name become AD's, `source` becomes
  `ldap`, and **its `id` never moves** — so every issue, comment and worklog stays
  attached to the same person. This is the answer to "it should overwrite email
  and such".
- **`merge`** — two accounts. The look-alike is folded into the AD-identified one
  through the existing `merge_users` (everything repoints; the source is
  deactivated, kept for audit), then the survivor takes AD's values.
- **`create`** — deliberately keep both (they really are two people).
- **`skip`** — import nothing for them.

An email with no resolution keeps the pre-88 behavior (create-or-link, existing
accounts untouched), so the endpoint stays backward compatible.

## Deliberate choices

- **Nothing auto-resolves.** A name collision is a heuristic — two people share a
  name often enough — and silently rewriting an account's email address is not
  something to infer. The preview *suggests* (`merge` when both accounts already
  exist, otherwise `overwrite`), and a human confirms.
- **Overwrite preserves the row.** Deleting the legacy account and creating a
  fresh one would satisfy the wording and lose the person's history; keeping the
  `id` is the entire point.
- **The password hash is left alone.** Clearing it would lock out anyone
  mid-migration who still signs in locally, and the directory login path keys on
  email regardless.
- **`source` becomes `ldap`.** The account is directory-governed from then on:
  the user sync may rename it, and — if `ldap_user_sync_deactivate_missing` is on
  — deactivate it when the person leaves AD. That is the intended meaning of
  "keeping the AD entry", and worth knowing before overwriting a local account.
- **Overwrite refuses to steal an email** already held by another account (409
  naming `merge` as the alternative) rather than letting the unique constraint
  raise a 500.
- **Per-row failure.** One bad decision reports on its own row; the rest of the
  batch still applies.

## Frontend

`ImportUsersDialog` becomes select → **review** → import.
`DirectoryImportReview` lists only the conflicts (new/linked collapse to a count,
since nothing about them is ambiguous), each with its matched accounts, the
reason for each match, and radio choices. Every row spells out the consequence in
plain language — *"jsmith@old-domain.example becomes jsmith@corp.example — same account,
so all their issues, comments and worklogs follow"* — because these are
irreversible and easy to misread. Choices are pre-seeded with the server's
suggestion, so importing straight through does the sensible thing.

## The one-off cleanup: `scripts/reconcile_ad_users.py`

The interactive dialog handles ongoing imports, but an instance seeded by the
Jira importer needs the whole roster reconciled at once. The script buckets
**every Radd account** using the same planner, so there is one definition of
"these are the same person":

- **ENFORCE** — the account is already at its exact AD address. Adopt AD's name
  and mark it `source=ldap`, so the sync governs it from then on. This is what
  makes the sync stop being a no-op.
- **MERGE** — matches an AD person by display name only (a placeholder address
  like `alex.webb@example.com`). Fold it into the AD-identified account.
  An **unambiguous** name match only: if AD holds two people with that display
  name, the row drops to KEEP rather than guessing.
- **KEEP** — no AD counterpart. Leavers, sister-studio staff and service accounts
  all land here, so the script never touches them; it reports and stops. Retiring
  them is a judgment call, not a reconcile.

Dry-run by default, `--apply` writes and records every touched account's
before-state to a timestamped JSON audit file. `--enforce-only` / `--merge-only`
split the two halves; `--exclude EMAIL` (repeatable) holds back individual rows.

A merge whose surviving AD account is **deactivated** is flagged in the report
but allowed (user direction): the work still repoints to the right person, and
whether they should have access is a separate decision on the Users page.

## Tests

`tests/test_ad_user_import.py` — the classification matrix (new / linked /
username-conflict / conflict-plus-exact / name-only / one-match-per-account) and
the write verbs: overwrite preserves the id and adopts AD's identity, overwrite
refuses a taken email, merge folds the look-alike and deactivates it, merging an
account into itself is refused, skip writes nothing, and overwrite/merge require
a target.

Unrelated fix in the same pass: `test_user_sync_base_cascade_override_beats_env`
asserted that no instance-scope `ldap_user_sync_base` existed, so it began
failing the moment a real deploy saved one through the Directory page. It now
clears the key inside its own rolled-back transaction — configuring the product
must never fail its own tests.
