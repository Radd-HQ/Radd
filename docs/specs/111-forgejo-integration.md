# Spec 111 — the Forgejo integration rebuilt: connections as rows, history backfilled, builds visible

**.** Spec 47 shipped a webhook receiver configured by one environment secret.
It links what happens *after* someone remembers to register the hook, knows
nothing about the host it is talking to, and cannot answer the first question
anyone asks of a linked issue: did the build pass. Radd now runs its own
development on a Forgejo it controls, so the integration stops being a
connector and becomes a first-class one, on the pattern specs 100–102 set.

## Why

The existing module (`modules/forgejo`) is 120 lines of router plus a pure
parser. What it does is right — `\b[A-Za-z][A-Za-z0-9]{0,9}-\d+\b` over commit
messages, branch names, PR titles and bodies, upserted through the `vcs`
write-seam as the system actor — and none of that changes. What it lacks:

- **One host, in the environment.** `RADD_FORGEJO_WEBHOOK_SECRET` is a single
  string. A second Forgejo, a rotated secret, or an admin who wants to see
  whether the thing is even connected all require a redeploy. Jira connections
  (spec 100) and AI providers (spec 101) already moved to rows; this is the
  same move, and the env key becomes SEED-ONLY (the spec-101 rule).
- **No history.** The connector is deaf to everything that happened before it
  was registered. The RADD project was just backfilled with five months of
  issues whose real commits exist in a repository we can read — and the
  integration has no way to attach them.
- **No repository identity.** Payloads name `owner/repo`; Radd stores a URL and
  a title. Nothing records that `Radd/Radd` is the RADD project's repository, so
  the version-control panel cannot group, filter, or say where a link came from.
- **No build state.** `item_vcs_links.status` carries the PR's open/merged/closed
  and nothing else. "Is this branch green" is the question a reviewer actually
  has.

## What

- **`forgejo_connections`** rows: `name`, `base_url`, `api_token` (redacted on
  read, empty-on-update keeps — the AI-provider convention), `webhook_secret`,
  `active`, timestamps. `RADD_FORGEJO_WEBHOOK_SECRET` seeds ONE row on first
  boot and is inert afterwards. CRUD gated on new atoms `vcsconn.create` /
  `.update` / `.delete`, contributed through one `CRUD_RESOURCES` line and
  implied by `global.manage`.
- **`forgejo_repos`** rows: `connection_id`, `full_name` (`owner/repo`,
  unique per connection), `project_id` (nullable FK — a repo may serve several
  projects, so this is the DEFAULT, not a constraint), `default_branch`,
  `last_backfill_at`. **Key resolution stays global**: project keys are unique
  instance-wide, so `RADD-412` in any repo finds the item. The mapping exists for
  scoping (which project's releases a tag creates — spec 112), display, and
  backfill targeting; it never narrows what a webhook may link.
- **The receiver resolves its connection from the payload.** `repository.full_name`
  → `forgejo_repos` → connection → verify the HMAC with THAT connection's secret.
  An unknown repository falls back to trying each active connection's secret, so
  a hook registered before its repo row still works; a failing signature against
  every candidate is a 403, as today. An inactive connection is ignored.
- **Events.** `push` and `pull_request` keep their current parsing. Added:
  `release` (consumed by spec 112), `create`/`delete` (branch and tag lifecycle,
  so a deleted branch's link is marked stale rather than lingering), and
  `workflow_run` / `workflow_job` where the host emits them (Forgejo Actions).
  An unhandled event returns `{"linked": 0}` and is not an error.
- **CI status on the link.** `item_vcs_links` gains `ci_state`
  (`success|failure|running|cancelled|unknown`), `ci_url`, `ci_updated_at` —
  the LATEST run for that ref, not a check-run history. Fed by `workflow_run`
  webhooks when available and by the backfill/poller otherwise. Rendered as a
  chip in the version-control panel next to the ref.
- **Backfill.** `POST /forgejo/repos/{id}/backfill` walks the Forgejo API —
  branches, pull requests (open and closed, paginated), and commits on the
  default branch bounded by `since`/`max_commits` — extracts keys with the same
  parser, and upserts through the same seam. It is a staged background job with
  live progress, the jiraimport shape, and it is IDEMPOTENT: `external_id`
  dedup means running it twice links nothing twice. Reads only; a token needs
  no write scope.
- **Settings → Forgejo** (admin): connections with a Test button (calls
  `/api/v1/version` and reports the host's version), repositories with their
  project mapping and last-backfill time, and a Backfill action with progress.

## Invariants tested

- A payload's signature is verified against its OWN connection's secret; a
  secret from another connection is refused.
- An inactive connection ignores webhooks entirely.
- A key referencing an unknown item is skipped silently, and the rest of the
  payload still links (unchanged from spec 47).
- Backfill run twice produces the same link set — `external_id` dedup holds
  across webhook-created and backfill-created links.
- The repo→project map does not affect key resolution: a `RADD-1` reference in
  an unmapped repository still links.
- `ci_state` reflects the most recent run for the ref, and a later run
  overwrites an earlier one rather than accumulating.

## Known simplifications

- **No write-back.** Radd does not comment on the PR or set commit statuses.
  Deliberate for now: it needs a write-scoped token per host and an opinion
  about noise. The connection row already has somewhere to put that token.
- Commit backfill walks the default branch only. Commits that reached a PR but
  never merged are covered by the PR walk, not the commit walk.
- CI status is per-ref-latest. A branch with two workflows shows the last one to
  report, not both.
- One Forgejo API page size, fixed backoff, no ETag caching. The repositories
  this serves are small.
