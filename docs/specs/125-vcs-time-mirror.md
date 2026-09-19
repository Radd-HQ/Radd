# Spec 125 — Time logged on merge/pull requests, mirrored into the issue

RADD-1257 (epic), 2026-09-19. Children: RADD-1258 (the seam), RADD-1259 (GitLab),
RADD-1260 (Forgejo), RADD-1261 (GitHub), RADD-1262 (one Version control page).
Built alongside RADD-1253/1254 (GitLab connections as rows, canonical ids) from
the GitLab-rebuild epic RADD-1252, which the GitLab half needed.

## Why

A developer who logs time on a merge request in GitLab (`/spend 1h30`) or on a
pull request in Forgejo should not have to type it a second time into Radd. The
connectors already link the MR/PR to the issue by key mention; the time should
ride that link — attributed to the person, on the day it was spent.

Two requirements set the shape: **historical import** (time logged before the
webhook existed must come in through the connector's backfill) and **never
twice** (a backfill after a webhook, a re-delivered webhook, three backfills in
a row: one worklog per source entry).

## What each host offers

| Host | Native time | How we learn of a change | Per-entry read | Author email |
|---|---|---|---|---|
| GitLab 18.4 | `/spend` on MRs → `Timelog` rows | MR webhook `changes.total_time_spent` | GraphQL `mergeRequest.timelogs` | `publicEmail`, else REST `/users/:id` (admin token) |
| Forgejo/Gitea | tracked time on issues and PRs | none — reconcile on every PR delivery + backfill | REST `/issues/{index}/times` | `/users/{username}` when visible |
| GitHub | **none** | `issue_comment` / review comment webhooks | a `/spend` comment convention | hidden; commit-author emails fill the map |

## The seam (RADD-1258)

`worklogs` gains provenance: `external_source` (VcsProvider), `external_scope`
(the ref's vcs external id, `pr:<repo>:<n>`), `external_id` (the host's own
entry id), under a partial UNIQUE index on `(external_source, external_id)`.
That index — not a lookup — is the "never twice" guarantee, the
`uq_item_vcs_links_ref` precedent (RADD-1124).

`timelogging/external.py` exposes `reconcile_external_worklogs(source, scope,
entries)`: upsert every entry by external id (savepoint insert → update on the
index conflict), delete the mirrored rows under that SCOPE the source no longer
has, skip items whose project has time logging off. Deletion is scoped by the
ref, never the item, because one issue may receive time from several MRs.
`authorize_mutation` refuses update/delete on a mirrored row for everyone,
admins included: the entry is corrected where it was logged, and the next
reconcile brings the correction over.

`vcs/timemirror.py` is what a connector calls. It decides:

- **which issue** — the first key across the ref's texts, in order (source
  branch, title, description), that names a real item. One item, never a split;
  an entry whose own summary names a key overrides for that entry.
- **who** — an existing `vcs_user_links` row for this connection; else a Radd
  account with the same email, recorded as an email-matched row so the admin
  can see and override it; else nobody. An entry with no author is parked in
  `vcs_pending_worklogs` and appears in Settings as an unmatched account. It is
  never attributed to SYSTEM or guessed: a worklog on the wrong person makes the
  timesheet lie.
- **what category** — the repository's `time_category_id`, else the instance's
  `Development`, else none.

Mapping an unmatched account replays its parked entries into real worklogs by
external id, so a later reconcile from the source finds the same rows.

## Forgejo (RADD-1260) and GitHub (RADD-1261)

Forgejo reconciles a PR's tracked time on every `pull_request` delivery and in
the backfill — there is no webhook for tracked time. Entries are dated by when
they were added (Forgejo has no "spent on"), and the note says so.

GitHub's `/spend` convention is read from PR comments and reviews. Each comment
owns its rows (`comment:<repo>:<id>:<n>`), so an edited comment updates the
same rows and a deleted one removes them; the seam's `id_prefix` narrows the
reconcile's deletion to that comment, because a single comment event cannot
know the PR's other comments. `/unspend` forgets the author's rows on the PR.
The identity map fills itself from push commit-author emails, the one place
GitHub pairs an email with a login.

## Rejected

- Attributing unmatched time to the connection's service identity: pollutes
  per-person reports.
- Splitting an MR's time across every mentioned issue: fabricated proportions.
- A GitHub Marketplace time app as the GitHub path: an external dependency for
  what a regex handles.
- Reconciling per item instead of per ref: would delete MR B's rows when MR A
  reconciles on the same issue.

## Traps found on the way

- **The `vcsconn.*` atoms lived on forgejo's manifest** while GitHub (and now
  GitLab and the vcs admin routes) gated on them; disabling Forgejo would have
  removed the atoms from under three other surfaces. They moved to `vcs`, which
  is always loaded; `test_permission_ownership` still holds (one owner per atom).
- **Load order:** `vcs` now depends on `timelogging`, so it moved after it in
  `config.modules`. Nothing between the two depended on `vcs`.
- **Two ratchets bit immediately:** `test_item_merge` demands a disposition for
  every FK to `work_items` (`vcs_pending_worklogs.item_id` → repoint) and
  `test_merge_coverage` for every user-bearing column (`vcs_user_links.user_id`
  → plain repoint; the unique key is the username, so no collision).
- **GraphQL lives at `/api/graphql`**, not under `/api/v4` — the first probe
  404ed.
- **GitLab writes a NEGATIVE timelog for `/remove_time_spent`** (and the REST
  `reset_spent_time`) rather than deleting rows. The first live run dropped the
  negatives and mirrored 2h35m onto an MR GitLab reported as 0. `net_entries`
  now folds a negative into the most recent live entries before it (LIFO), in
  CREATION order — not `spentAt` order, because a dated `/spend 45m 2026-09-18`
  logged before a reset sorts earlier by date and would have let the reset eat
  entries added after it. The fold sums to GitLab's own `totalTimeSpent`.
- **`spentAt` for a dated `/spend 1h 2026-09-18` is NOON UTC on that date**
  (18.4); an undated one is the moment it was typed. The date part is read in
  UTC and never shifted — the timesheet buckets by calendar day.
- **GitLab masks `X-Gitlab-Token` as `[REDACTED]` in its recorded hook
  deliveries**, so a replay must carry the real secret. And this workstation's
  ufw blocks inbound 8000, which is why GitLab's own deliveries never arrived;
  the receiver was proven by replaying the recorded payloads.

## Settings (RADD-1262)

One **Version control** page with a tab per host kind (Forgejo, GitHub,
GitLab), URL-carried (`?host=gitlab`), the way Import data holds Jira and
Confluence. The old `/settings/forgejo` and `/settings/github` paths redirect to
the tab, so bookmarks and the audit ledger's "change history" links keep
working. Each connection carries a **Time-tracking identities** section: the
mapped accounts (email-matched or by hand) and the unmatched ones with a
map-and-log action; each repository a default work category.

## Proof

`server/tests/test_time_mirror.py` (the seam, 13), `test_gitlab.py`,
`test_gitlab_connections.py`, `test_gitlab_timelogs.py` (MockTransport over the
18.4 shapes verified against Cinesite's GitLab). Live: a repository under
Hussein's personal namespace on `gitlab.mtl.ad.cinesite.com` — never an IT or
INFRA project.
