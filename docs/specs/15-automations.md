# Spec 15 — automations: event-driven rules engine (backend, Wave 2)

Depends on spec 14 (cycle/release actions). Allowed paths: `server/src/radd/modules/automations/`
(new), `server/src/radd/modules/auth/authz.py` (add `Permission.AUTOMATION_MANAGE`),
`server/src/radd/config.py` (modules tuple), `server/migrations/versions/` (ONE revision),
`server/tests/test_automations.py` (new — the match/apply core), `server/scripts/demo_automations.sh`
(new), `docs/modules.md`.

A sibling migration head may exist (spec 17 runs in parallel) — use `alembic upgrade heads`, do NOT
merge (supervisor merges). Never touch port 8000; verify on 8001/8002, kill exact PIDs. Explicit
pathspec commits.

## Model

- `automation_rules`: id, workspace_id FK, name, enabled bool default true, trigger
  (`AutomationTrigger` StrEnum: item_created | item_updated), condition_slq (Text, default '' =
  always; compiled+validated on write against the workspace registry → 422 {detail, position}),
  actions (JSONB list of `{type, params}`), position int, timestamps.
- `ActionType` StrEnum + a validated pydantic union: `set_state` (state name in the item's project),
  `set_priority`, `set_assignee` (email|none), `set_team` (name|none), `add_label`, `remove_label`,
  `set_cycle` (name|none), `set_release` (version|none), `set_custom_field` ({key,value}),
  `add_comment` ({body, visibility}). Validate action params on rule write where cheap; resolve
  names→ids at apply time (skip+log an action whose target no longer resolves).

## Engine (event-stream consumer, mirrors the webhooks dispatcher)

- New consumer offset `automations.engine`; a background task (module `on_startup`/`on_shutdown`,
  same shape as `webhooks/dispatcher.py`) polls the outbox, and for each `item.created`/`item.updated`
  event: load enabled rules for the event's workspace whose `trigger` matches; for each, evaluate
  `condition_slq` against THAT item (reuse the SLQ compiler with an `id = <item>` guard, or run the
  compiled query filtered to the one item id — must reuse `items/slq`, not reimplement); if it
  matches, apply the actions via the items/comments/labels/cycles/releases **services** as a system
  actor (`actor_id=None` or a dedicated marker).
- **Loop guard (critical):** applying actions emits new `item.updated` events. Prevent infinite
  loops — options: tag automation-caused events (add an `automation_rule_id` to the emit payload and
  skip events already automation-caused), or cap re-trigger depth per originating event. Implement
  one and TEST it (a rule that sets a field the rule also matches on must not loop).
- Actions run in one transaction per event; a failing action logs and continues (best-effort),
  does not crash the engine.

## Endpoints

CRUD `GET/POST/PATCH/DELETE /automations?workspace_id=` gated on `AUTOMATION_MANAGE` (grant it to
workspace admins + builtin admin role only). `POST /automations/{id}/test` {item_id} → dry-run:
returns which actions WOULD apply (no writes) — powers a UI preview. Events
`automation.created/.updated/.deleted`.

## Verify (demo_automations.sh, 8001)

Seed+login; create a rule (trigger item_created, condition `priority = blocker`, action add_label
"urgent" + set_state to a review state); create a matching item and a non-matching one; show the
matching one got the label/state and the other didn't (poll briefly for the async engine); show the
loop guard (a rule keyed on its own effect doesn't spin); `POST /automations/{id}/test` preview.
`uv run pytest` green; demo.sh/demo_webhooks.sh/demo_permissions.sh/demo_views.sh regression green.

Report: migration id, loop-guard mechanism, verification output, deviations, gaps.
