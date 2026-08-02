# Spec 72 — Request participants (users + teams)

Target-features wave, part 5. Participants on an item: users added directly AND
whole teams — the reporter of a request can share their ticket with a team they
belong to, and everyone the item is shared with follows it. Participation is a
NOTIFICATION/visibility-lite concept: it rides the existing watcher + notify
machinery, it does not change RBAC.

## 1. Data (items-adjacent module `participants`)

- `item_participants`: id, item_id FK CASCADE ix, exactly-one-of user_id /
  team_id (CHECK, the `view_shares` idiom), added_by FK users, created_at,
  unique (item_id, user_id) / (item_id, team_id). User-merge dedupes like
  view_shares.

## 2. API

- `GET /items/{id}/participants` (item.read) → `{users: [...], teams: [...]}`
  hydrated refs.
- `POST /items/{id}/participants {user_id | team_id}` — allowed for actors
  with `item.update` OR the item's REPORTER (the point of the feature: a
  requester shares their own ticket; reporter check is by identity, not
  permission). Subject must belong to the item's workspace (409).
- `DELETE /items/{id}/participants/{participant_id}` — same gate, plus a USER
  participant may remove THEMSELF (leave).

## 3. Semantics

- Direct-user participants are auto-watched on add (`item_watchers` row, the
  notify consumer already fans to watchers) — one mechanism, no parallel
  fan-out path.
- TEAM participants stay LIVE: the notify consumer's recipient computation
  unions in `participants.team_recipient_ids(item_id)` (current team members
  at fan-out time) — so joining a team joins its shared tickets. Members
  removed from the team stop receiving without cleanup rows.
- Recipients still pass the existing `item.read` + internal-comment filters —
  participation never widens what someone may see.
- Events: `item.participant_added` / `item.participant_removed` (entity item,
  payload user/team display refs) → History feed + automations catalog
  (Service-desk group).

## 4. Frontend

- Properties rail: a Participants section (always-on conditional, under the
  requester chip): user avatars + team chips, an add popover (user search +
  team select tabs), × to remove where permitted, "Leave" for yourself.
- The reporter path works from the panel too (reporter sees the add control
  even without item.update).

## 5. Tests

- reporter (non-privileged) can add a team; random member without item.update
  cannot; self-leave works.
- notify fan-out reaches a team participant's CURRENT members and skips a
  member who left the team; direct participant auto-watch row created.

## Known simplifications

- No per-participant notification granularity (they get watcher-grade
  notifications; user prefs already allow muting types).
- Mail contacts (external requesters) stay single per item (spec 62);
  participants are INTERNAL users/teams.

## As-built notes

- NEW module `radd.modules.participants` (last in `RADD_MODULES`, after
  approvals) — `__init__/types/models/schemas/service/router`, the approvals
  module shape. Migration `4e66edf3f951` (spurious `ix_doc_pages_fts`
  drop/create lines deleted from both directions, as usual).
- The exactly-one-of is DB-ENFORCED here (unlike `view_shares`, which is
  service-level): CHECK `ck_item_participants_one_subject`
  (`(user_id IS NULL) != (team_id IS NULL)` — named `one_subject` in the model
  so the `ck_%(table)s_%(name)s` convention doesn't double the prefix) plus the
  schema-level exactly-one validator on POST (422). Unique (item,user) +
  (item,team) coexist happily with NULLs (Postgres NULLS DISTINCT).
- `GET /items/{id}/participants` returns `{users, teams, rows, can_manage}` —
  `rows` carry grant ids for DELETE and hydrated `user`/`team`/`added_by`
  refs (items' `UserRef` with avatar fields, reused, like approvals reuses
  `ItemUpdate`); `can_manage` is computed per actor SERVER-side
  (item.update ∨ actor == reporter) so the reporter path needs no client
  permission logic. Self-leave (a user row whose `user_id` == actor) bypasses
  the gate on DELETE only.
- Subject validation copies the approvals rule-write precedent: user must be
  active + a member of the item's workspace (instance admins pass without a
  membership row), team must be same-workspace — 409; dupe 409.
- Auto-watch on direct-user add goes through `notify.add_watchers`
  (idempotent, no event — the manual `watch()` would emit `item.watched` as
  the SUBJECT, which they didn't do). Team members are deliberately NOT
  watched individually.
- The notify union landed as `consumer.recipient_ids(session, item_id)` —
  watchers ∪ `participants.team_recipient_ids` behind a deferred
  try/ImportError — swapped in at the three watcher-read fan-out sites
  (item-updated, comment, SLA). `team_recipient_ids` resolves members via
  `teams.list_team_members` per participant team (public service fns only, no
  cross-module table join). `_allowed` (item.read + internal-comment
  filtering) still runs per recipient, so participation never widens
  visibility; inactive users drop there too.
- Events `item.participant_added/.removed` are entity_type=item (csat/
  approvals precedent — NO `RELATED_EVENT_TYPES` entry); payload carries
  `user`/`team` refs + a scalar `participant` display name, and history's
  `_DETAIL_KEYS` gained `participant` + `team` so the History verbs render
  ("added the Desk team as participants"). Both events are Service-desk
  automation triggers (item-scoped).
- User-merge: `item_participants` joined auth's `_MERGE_DEDUPE`
  ((item_id, user_id) — drop-then-repoint like `item_watchers`) and
  `_MERGE_REPOINT` (`added_by`).
- Frontend: `ParticipantsSection` in the Properties rail between the external-
  requester chip and CSAT — renders whenever there are rows OR the actor
  can_manage (add affordance on empty); avatar chips for users, a Users-icon
  chip for teams, × per row where permitted, "Leave" on the actor's own direct
  row, and a toggled add panel with two filtered selects (active non-
  participant users / non-participant teams). `participantsQuery` tagged
  `Entity.item` (realtime invalidation free), paths in constants
  (`apiItemParticipantsPath`/`apiItemParticipantPath`), types
  `ParticipantRow`/`ItemParticipants`.
- Tests: `server/tests/test_participants.py` (3) — reporter-identity gate
  (add team + user without item.update; bystander 403; self-leave),
  live team fan-out through `consumer.recipient_ids` + planner (leaver drops
  without cleanup rows; auto-watch row asserted; team members NOT
  individually watched), workspace-mismatch/outsider/dupe 409s.
