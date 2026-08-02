# Spec 112 — the release pipeline: work finishes once, ships later

**.** "Done" answers the developer's question. The person who filed the issue is
asking a different one: is it running yet. This spec separates the two — a
`Waiting for release` state that means the work is complete, and a published
Forgejo release that turns every waiting item into a shipped one, with the
version recorded.

## Why

The RADD project already carries a transition guard (spec 107) refusing entry to
`Done` unless a release is set. Nothing sets it, so the guard is a wall: the
backfill had to name a release explicitly on 598 items to get past it. That wall
is the right instinct with no machinery behind it.

Meanwhile the release side is manual. Radd tags a version, CI publishes an
image, CD rolls it out — and the tracker learns none of it. The information
exists at a precise moment (a Forgejo release is published) and nothing carries
it across.

The state has to sit in the **`done` category**, not `in_progress`. Categories
drive analytics: throughput counts entry into a done-category state, and the
honest answer to "when was this finished" is the day the work was finished, not
the day someone cut a tag weeks later. An item waiting for release is finished
work that has not shipped — closed on the board, open in the release.

## What

- **A seeded `Waiting for release` state**, category `done`, positioned
  immediately before `Done`. New projects get it in the seed set; existing
  projects add it from Settings → States (and the RADD project gets it as part
  of this work).
- **Two project settings** name the states, so nothing is matched by string:
  `release_waiting_state_id` and `release_shipped_state_id`, both in the
  settings cascade (spec 67). Unset = the pipeline is off for that project, and
  the module does nothing. This replaces `RADD_FORGEJO_MERGE_TRANSITION_STATE`,
  an env var holding a state NAME matched per project — which was always a
  guess.
- **PR merged → waiting.** Spec 47's merge transition now moves the referenced
  items to the project's `release_waiting_state_id`. Same trigger, data-driven
  target, per project instead of instance-wide.
- **A published release creates the Radd release.** The `release` webhook
  (spec 111) with action `published` calls `releases.service.create_release` for
  the repository's mapped project: `version` = tag name, `name` = release title
  or tag, `status` = `released`, `description` = the release notes, truncated.
  A tag that already exists as a version is reused, not duplicated — the event
  is at-least-once.
- **The sweep.** On that same event, every item in the project sitting in the
  waiting state moves to the shipped state with `release_id` set, as the SYSTEM
  actor — which is exactly what the existing guard demands, so the guard starts
  passing instead of blocking. Items already shipped are untouched.
- **`POST /releases/{id}/sweep`** does the same thing on demand, so the pipeline
  works on an instance with no Forgejo at all, and so a missed webhook is one
  button rather than 40 manual edits. Gated on `release.update`.
- **Attribution.** Every write is the system actor with the release named in the
  event payload, so the item history reads "Automation moved this to Done,
  release 0.3.0" rather than an anonymous state change.

## Invariants tested

- The sweep is idempotent: running it twice moves nothing the second time.
- An item already in the shipped state keeps its original release; the sweep
  does not repoint it.
- Entry into `Waiting for release` is what throughput counts — the later move to
  `Done` does not count the item a second time (both are category `done`, and
  the timeline collapses same-category transitions).
- A `release` event for a repository with no project mapping is a no-op, not an
  error.
- A duplicate `release` webhook for an existing tag reuses the version row.
- With the settings unset, the merge transition and the sweep both do nothing —
  a project that does not want the pipeline is unaffected.

## Known simplifications

- **The sweep takes everything waiting**, not the items whose commits are
  actually in the tag range. Deriving that needs a commit walk between two tags
  and a link back through `item_vcs_links` — real work, and only correct if
  every merge went through a linked PR. The simple rule matches how a
  single-stream project actually ships; the precise one is a later increment,
  and spec 111's backfill is the machinery it would stand on.
- One project per repository for release purposes (the `forgejo_repos.project_id`
  default). A monorepo serving several projects would need the sweep to take a
  project list.
- Release notes are stored verbatim and truncated; no markdown normalization.
