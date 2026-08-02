# Spec 58 — Automations: any-event triggers + structured event conditions

**Status: built.**

## Problem

Rules could only fire on `item.created`/`item.updated` and could only filter on the
item's *current* state (SLQ). There was no way to react to comments, worklogs, or any
other entity's events, and no way to condition on the *change itself* — which field
changed, what it changed to, or who did it.

## Shape

- **Trigger = any catalog event type.** `automation_rules.trigger` widened to the raw
  event-type string ("item.updated", "comment.created", … — data-migrated from the old
  `item_created`/`item_updated` enum values; `"manual"` unchanged). `catalog.py` curates
  the ~52 subscribable types with UI metadata (label, group, `item_scoped`,
  `has_changes`); writes validate against it. `GET /automations/catalog` serves
  triggers + subjects + operators so the builder renders entirely from the server.
- **Event conditions** (`event_conditions` JSONB, nullable): a nestable `all`/`any`/
  `none` tree of `{subject, qualifier?, operator, value?}` leaves evaluated against the
  triggering event — before the SLQ item condition. Subjects:
  - `actor` — matches the causing user's id, email, or name;
  - `changed_field` — names from the `item.updated` diff (custom fields by key);
  - `old_value`/`new_value` — a named field's `from`/`to` (labels/links resolve
    `removed`/`added`); unresolved when the field didn't change → `is_set`/`not_set`;
  - `state_category` — the item's post-event state category (payload `state.category`);
  - `payload` — dotted path into the raw payload, lists fan out.
  Operators: eq/neq/in/not_in/contains/not_contains/is_set/not_set/matches (regex,
  case-insensitive)/gt/lt. Strings compare case-insensitively; numbers numerically.
  Guards: depth ≤ 5, nodes ≤ 50 (enforced on write and again at eval).
- **Engine**: `should_process` covers every catalog type (still skipping the system
  actor — the loop guard is unchanged). The target item resolves from the event entity
  or the payload's `item_id` (the stream-wide convention: comments, worklogs,
  attachments, vcs/web links, sla.breached). Itemless triggers (cycles, docs, admin)
  evaluate event conditions but skip item actions with a log — actions are all
  item-bound today; non-item actions are the designed extension seam.
- **Purity**: `conditions.py` is session-free (`EventFacts` in, bool out), unit-tested
  in `tests/test_automation_conditions.py`; the engine builds facts once per event
  (actor row resolved to id/email/name).
- **UI**: the rule editor picks triggers from the grouped catalog, and a recursive
  ALL/ANY/NONE condition builder (subject/qualifier/operator/value rows, nested groups)
  sits between the trigger and the SLQ box. Trigger labels everywhere come from the
  catalog.

## Verified

Pure evaluator suite (12 cases: subjects, operators, nesting, label/custom-field diff
shapes, guards) + live E2E: a `comment.created` rule conditioned on actor + payload
visibility fired only for the matching comment; an `item.updated` rule conditioned on
`changed_field contains state AND state_category = done` ignored a title-only edit and
fired on the move to Done.

## 58b — universal actions (same day)

Four actions that run for EVERY matching event, item or not (`ITEM_ACTIONS` in
types.py is the item-bound registry; everything else is universal):

- **create_item** — project key + templated title/description (+priority); the
  emitted `item.created` carries the system actor, so the loop guard holds.
- **send_webhook** — POSTs the machine payload `{rule, event_type, actor, item,
  payload}`; optional secret → HMAC-SHA256 hex in `X-Radd-Signature` over the
  exact body bytes (sorted-key compact JSON).
- **post_chat** — POSTs `{"text": message}` to a Google Chat/Slack-style
  incoming webhook, message templated.
- **notify_user** — in-app notification (`NotificationType.AUTOMATION`, payload
  `{message, rule}`; new inbox row + mute option in notification prefs).

Templates (`templating.py`, pure): `{{event_type}}`, `{{actor.id|email|name}}`,
`{{payload.<dotted>}}` (lists join ", "), `{{item.key|title|id}}` when a target
item resolved; unknown tokens stay verbatim. Item actions on itemless events
skip with a log; universal actions always run. HTTP uses `webhook_timeout`, one
savepoint per action as before. Verified live: a `cycle.created` rule fired all
four (receiver captured the templated chat text + a signature that re-verified
against the body; TD item created with templated title; inbox notification).

## Deliberately not done

- Rule-to-rule chaining stays impossible by design (single-hop system-actor guard).
- Value pickers (user/state autocomplete) in the condition builder — free text v1.
- Templates in ITEM action params (comment body etc.) — universal actions only for now.
