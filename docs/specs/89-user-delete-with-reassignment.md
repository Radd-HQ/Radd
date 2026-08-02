# Spec 89 — Deleting a user, with their work reassigned

**Status: shipped.**

User direction: *"I want to be able to delete local users, and when deleting them
get asked who should own everything that they did before."*

This **reverses a spec-87 decision**. That spec dropped the `user.delete` atom
with the reasoning that accounts are only ever deactivated or merged, so no
endpoint could exist behind it. That was wrong: deletion is a legitimate
operation, it just needs the authored work rehomed first. The atom is back.

## The shape

Two calls, because the consequences have to be legible before they happen:

- **`GET /users/{id}/content`** — what the account owns: issues reported and
  assigned, comments, wiki pages, views, dashboards, owned teams, attachments,
  approvals, plus worklog count and total seconds.
- **`DELETE /users/{id}?reassign_to=<uuid>`** — hard-deletes the row. Everything
  authored moves to `reassign_to`, which is **required whenever the account owns
  anything** (409 otherwise) and omitted freely when it owns nothing, so clearing
  out placeholder accounts stays one click.

The row genuinely goes — unlike `POST /users/{id}/merge`, which keeps a
deactivated shell for audit, and unlike `PATCH {active:false}`, which only
revokes access. The `user.deleted` event carries the email, name, successor and
what moved: once the row is gone, that event *is* the record they existed.

## Worklogs are deleted, not reassigned

Everything else follows the successor; time entries do not. Crediting someone
with hours they never worked would corrupt every timesheet and time report that
includes them — a silent data-integrity loss that is far worse than losing the
entries. The dialog states the count and total hours before you confirm.

## Making deletion actually possible

Deleting a user row means every reference to it must be dealt with first. Diffing
the merge machinery against the live schema found **three columns that would have
hard-blocked the delete** — and which were *already* a quiet bug in `merge_users`,
where a merged-away account kept holding them:

- `approval_requests.requested_by`
- `approval_votes.user_id`
- `doc_pages.updated_by`

Plus `teams.owner_id`, which is `ON DELETE SET NULL` — without an explicit
repoint, deleting someone would have silently orphaned the teams they owned
rather than handing them over. All four are now in `_MERGE_REPOINT`, so the fix
lands on merge and delete alike.

`tests/test_user_delete.py` asserts this against the **live schema**, not a
hand-written list: every FK to `users` with `NO ACTION`/`RESTRICT` must appear in
the repoint set. A new table referencing users can no longer quietly break
deletion.

Three tiers of reference, handled differently:

| kind | example | what happens |
|---|---|---|
| blocking FK (13) | `work_items.reporter_id`, `comments.author_id` | repointed to the successor |
| `CASCADE` (12) | sessions, tokens, MFA, stars, memberships, shares, global role grants | die with the account — personal state, not authored work |
| **no FK at all** | `events.actor_id`, `notifications.*`, `item_watchers`, `attachments.created_by` | would silently **dangle**, so they are repointed too |

That last row is the subtle one: those columns reference users without a
constraint, so Postgres would happily leave them pointing at a missing id. With a
successor they are repointed; without one (the owns-nothing path) personal rows
are purged and `events.actor_id` is nulled, keeping the audit row while dropping
the ghost link.

## Guards

- You cannot delete your own account (the actor would vanish mid-request — the
  same reasoning as the existing self-demotion 409).
- The successor must be active; a deactivated one would leave the work owned by
  someone who cannot access it.
- The successor cannot be the account being deleted.

## Frontend

`DeleteUserDialog` on the Users page: fetches the summary on open, lists what
moves, warns in amber about the worklogs being destroyed with their hour total,
and requires a successor only when something would otherwise be orphaned. The
confirm button stays disabled until that choice is made.

## Tests

`tests/test_user_delete.py` — reassignment of issues/comments with worklogs
discarded, successor required only when work exists, the pure guards, an owned
team following the successor, and the schema-driven completeness check above.
