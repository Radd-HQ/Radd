# Spec 31 — GitLab connector (the `vcs` stub made real)

Tier-2 item 6 from `docs/roadmap-ideas.md`: auto-linking MRs/branches/commits and
transitioning issues on merge is the payoff of the vcs module, and we're a GitLab
shop. The roadmap sketches an out-of-process extensions SDK; this spec ships the
pragmatic in-process version first — a webhook receiver module whose write path is
exactly the connector seam (`vcs.upsert_vcs_link`), so hoisting it into the future
out-of-process runner changes WHERE it runs, not what it does.

## Module: `radd/modules/gitlab/` — NO tables

### Endpoint

`POST /api/v1/integrations/gitlab` — point a GitLab project/group webhook here
(push events + merge request events). Auth = the `X-Gitlab-Token` secret header
compared (constant-time) against `RADD_GITLAB_WEBHOOK_SECRET`; empty setting =
connector disabled (403). No session/PAT — GitLab can't log in.

### Behavior (pure planning in `parsing.py`, tested in `tests/test_gitlab.py`)

Item keys (`TD-123`, case-insensitive, word-bounded) are parsed from:

- **push** — the branch name (→ a `branch` link per referenced item, external id
  `branch:<project>:<name>`) and each commit message (→ `commit` links keyed by sha,
  titled with the message's first line).
- **merge_request** — the source branch + MR title + description (→ a
  `merge_request` link, external id `mr:<project>:<iid>`, status = MR state).
  Re-delivery updates the same link in place (the upsert seam's find-or-create).

Unknown keys are skipped silently. All writes are attributed to the automation
system actor, so the automations engine's loop guard also covers connector-caused
events.

### Merge transition

When an MR event reports a merge and `RADD_GITLAB_MERGE_TRANSITION_STATE` names a
state (e.g. `Done`), every referenced item is moved to its project's state of that
name (resolved per project; missing name or already-there = skip) via
`items.update_item` as the system actor — an ordinary `item.updated` with a
`changes` diff, so History/notifications/realtime all light up for free.

## Known simplifications

- Config is env-level (`RADD_GITLAB_*`) — per-workspace connector settings arrive
  with the extensions SDK.
- Pipeline events are ignored for now (MR/push cover the artist-facing flow);
  two-way comment sync is out of scope.
- The transition applies to every item the MR references, regardless of workspace
  (single-instance trust; the secret gates the endpoint).
- In-process like the other consumers; the out-of-process runner is the planned
  `extensions` module.
