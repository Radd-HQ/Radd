# Spec 69 — Scheduled automation triggers

> **Superseded in part (RADD-1265, 2026-09-19):** the trigger's `condition_slq`/`query` is gone — a `search.slq` node wired after the schedule trigger selects the items — and `{{matched_count}}` was deleted in favour of `{{items.count}}`. The rest stands.

Target-features wave, part 2. The automations engine gets a clock: rules can
fire on a schedule (interval / daily / weekly) instead of an event, and a
scheduled rule with a `condition_slq` runs its ITEM actions per matching item —
which is what makes "every Monday 9:00 create the ops checklist item", "remind
assignees of items due in 3 days", and "nudge stale items" all expressible with
ZERO new action machinery. Plus an SLA `due_soon` pre-breach event so escalation
rules can fire BEFORE the breach.

## 1. Trigger + schedule config

- `AutomationTrigger.SCHEDULE = "schedule"` joins `"manual"` as a sentinel
  trigger (raw event-type strings stay as-is). Rules with it carry a new
  nullable `schedule` JSONB column on `automation_rules`:
  `{kind: "interval", minutes: N>=5}` |
  `{kind: "daily", time: "HH:MM"}` |
  `{kind: "weekly", time: "HH:MM", weekdays: [0..6]}` (0=Mon, non-empty).
  `ScheduleKind` StrEnum; validated on write (422/409 per form-error idiom);
  `schedule` present iff trigger == schedule. Times are interpreted in
  `settings.scheduler_tz` (config, IANA name, default "UTC") — one instance
  clock, documented on the builder UI.
- `event_conditions` must be empty for scheduled rules (there is no event);
  `condition_slq` and `actions` keep their exact semantics.

## 2. The scheduler loop (bookkeeping separate from user data)

- New table `automation_schedule_state` (rule_id PK FK CASCADE, `next_run_at`
  timestamptz, `last_run_at` nullable) — engine bookkeeping, mirrors the
  sla_item_states pattern. Row (re)computed whenever a scheduled rule is
  created/updated/enabled (pure `schedule.py: next_run(cfg, now, tz)`,
  unit-tested: interval anchors on last_run/now; daily/weekly = next wall-clock
  occurrence strictly after now).
- `PeriodicLoop` (`automations.scheduler`, interval
  `RADD_AUTOMATION_SCHEDULER_INTERVAL` default 60s, gated `run_workers`): each
  tick, due rows (`next_run_at <= now`, rule enabled) → for each, EMIT a
  synthetic outbox event `automation.scheduled` (entity `automation`, payload
  `{rule_id, workspace_id, scheduled_for}`) and advance `next_run_at` in the
  SAME transaction — at-most-once per occurrence; a missed window (server down)
  fires once on the next tick, never replays a backlog.

## 3. Engine handling (`automation.scheduled` consumer path)

- The existing engine consumer special-cases `automation.scheduled`: it loads
  THE payload rule (skip if disabled/deleted) and — crucially — does NOT apply
  the system-actor loop-guard skip (the synthetic event is system-emitted by
  design; loop safety holds because scheduled runs themselves emit ordinary
  item events with the SYSTEM actor, which the EVENT-rule path still skips).
- Execution semantics:
  - `condition_slq` empty → run the rule's UNIVERSAL actions once, itemless
    (item actions skip+log, same as itemless event triggers today).
  - `condition_slq` set → compile it against the workspace registry and run
    the ITEM actions per matching item, capped at
    `settings.automation_schedule_max_items` (default 200, ordered rank) with
    a log line when the cap truncates. Universal actions run ONCE with the
    match count available to templates as `{{matched_count}}`.
- Actions run in per-item savepoints exactly like the event path.

## 4. SLQ relative dates (makes scheduled rules useful)

- The SLQ lexer/compiler gains relative date literals for date fields
  (`created`, `updated`, `start_date`, `target_date`, date custom fields):
  `today`, `today+3d`, `today-2w` (units d/w; evaluated at compile time
  against the server date). `target_date <= today+3d AND state.category !=
  done` is the canonical reminder rule. Suggest-values include `today`.

## 5. SLA `due_soon` (date-driven pre-breach)

- `sla_policies` gains nullable `warning_minutes` (int > 0). The SLA engine,
  which already recomputes timers on its clock, emits `sla.due_soon` (entity
  item, payload mirrors `sla.breached` + `remaining_seconds`) ONCE per
  item/policy/kind when `remaining <= warning_minutes` and the target isn't
  met/breached — bookkeeping via new `warned_response_at`/`warned_resolution_at`
  stamps on `sla_item_states`. Notify fans it to assignee+watchers as
  `sla_due_soon` (new NotificationType, muteable like the rest); the
  automations catalog lists it under Service desk, so escalation is
  "trigger: sla.due_soon → actions" with no scheduler involved.

## 6. API + UI

- Catalog: `GET /automations/catalog` gains the Scheduled trigger group +
  schedule-kind metadata; rule CRUD validates as §1. `RuleRead` carries
  `schedule`, `next_run_at`, `last_run_at`.
- Builder UI: trigger picker gets "On a schedule" → schedule editor (interval
  minutes/hours select, or daily/weekly time + weekday toggles), a hint line
  ("runs item actions for every item matching the SLQ filter, max 200"), and
  next/last-run display on the rules list. SLA policy editor gains a
  "Warn before breach" minutes field.

## 7. Tests

- `next_run` pure math (interval/daily/weekly, TZ, DST-adjacent wall clock).
- Scheduled rule with SLQ applies item actions to matching items only, capped;
  loop guard still skips event rules on the resulting system-actor events.
- `sla.due_soon` emitted once, not after met/breach, stamps persisted.

## Known simplifications

- One instance-level scheduler TZ (config), not per-workspace.
- Relative dates resolve at compile time — a saved VIEW using `today` shows
  results as-of query time, which is the intuitive reading anyway.
- No per-rule run-history UI (the outbox rows are the record).

## As-built notes

Shipped exactly as specced; migration `7b7fa7839f55` (automation_rules.schedule
JSONB, automation_schedule_state, sla_policies.warning_minutes,
sla_item_states.warned_response_at/warned_resolution_at — the spurious
`ix_doc_pages_fts` autogenerate drop was deleted as usual). 736 tests green
(720 pre-existing + 16 in `tests/test_scheduled_automations.py`).

- **Types/config.** `AutomationTrigger` StrEnum (MANUAL/SCHEDULE; the old
  `MANUAL_TRIGGER` constant stays as an alias), `ScheduleKind`,
  `SCHEDULE_MIN_INTERVAL_MINUTES = 5`, `UNIVERSAL_ACTIONS` (complement of
  ITEM_ACTIONS), `AutomationEvent.SCHEDULED`, `AutomationEntity.AUTOMATION`.
  Settings: `RADD_AUTOMATION_SCHEDULER_INTERVAL` (60s), `RADD_SCHEDULER_TZ`
  ("UTC"), `RADD_AUTOMATION_SCHEDULE_MAX_ITEMS` (200).
- **Timestamps are naive UTC**, not timestamptz — deliberate deviation from the
  spec letter: every other timestamp in the schema is naive UTC and the engines
  compare against naive `utcnow()`; mixing aware columns in would break those
  comparisons. `next_run` (pure, `automations/schedule.py`) takes/returns naive
  UTC and resolves wall-clock times through zoneinfo, so a DST change keeps the
  LOCAL time stable (tested against America/New_York's fall-back).
- **Validation split:** schedule SHAPE errors are 422 (pydantic
  `ScheduleConfig`, stored with `exclude_none` so the JSONB carries only the
  kind's own keys); the cross-field invariants (schedule iff schedule-trigger,
  no event_conditions on scheduled rules) are 409 via
  `service._check_schedule_consistency` — they involve the merged rule state on
  partial PATCHes, which pydantic can't see.
- **Scheduler emits with `actor_id = SYSTEM_ACTOR_ID`** ("system-emitted by
  design"); `engine.should_process` special-cases `automation.scheduled` before
  the loop-guard check, and `apply_event` diverts to `apply_scheduled` before
  the rule-lookup path. Scheduled matches are restricted to ACTIVE
  (non-archived) items in the rule's workspace — same candidate scope as the
  SLA engine.
- **`{{matched_count}}`** is merged into the facts payload for the
  universal-action pass and resolved as a bare top-level token in
  `templating.py`; the empty-SLQ pass renders it as 0.
- **due_soon** reuses the breach plumbing: shared `_sla_payload` +
  `remaining_seconds`, pure predicate `evaluation.due_soon`, fired-once stamps,
  and notify's `plan_sla_breached` gained a `type_` parameter instead of a
  duplicate planner (`_handle_sla_event` handles both event types). A target
  already breached at first evaluation warns never — the breach event is the
  signal.
- **UI.** RuleEditor: "Scheduled" optgroup → `ScheduleEditor`
  (interval-preset select / time input / weekday chips, instance-clock note,
  per-item-run hint), SLQ label/placeholder switch to the reminder-rule idiom
  (`target <= today+3d AND category != done`); rules list shows
  `next … · last …` chips (`shortDateTime` added to lib/dates.ts).
  SlaPolicyForm: "Warn before breach (minutes)"; policy summary shows
  "warn Nm before". Inbox/prefs list the new `sla_due_soon` type.
- The pre-existing suggest test asserting date fields offer ONLY the format
  hint was updated: they now lead with `today`.
- Not built (matches the spec's silence): no dedicated scheduler-loop
  integration test (`scheduler.run_once` is thin glue over the tested
  `next_run` + engine path, and it commits — the test idiom is
  rollback-only); no PolicyUpdate UI for warning_minutes (the SLA editor is
  create+list, as before).
