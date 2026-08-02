# Spec 30 — Service desk: reporter, SLAs, canned responses

Tier-2 item 5 from `docs/roadmap-ideas.md`: TD is a de-facto service desk (~122
issues/week of artist support). This spec adds the requester model, SLA timers with
breach alerting, and canned replies. **Queues** are already covered by saved views
(SLQ like `reporter != me AND category = triage`); a queue-oriented list skin can
come later. **Email-to-issue intake is deferred** (needs inbound-mail infrastructure).

## 1. Reporter (items module change)

- `work_items.reporter_id` (nullable FK users, indexed) — who RAISED the issue,
  distinct from assignee. **Defaults to the acting user on create**; settable on
  create/update (`item.update`) for filing on someone's behalf. Intake-form submits
  get the submitter automatically (forms call `create_item` with the submitter).
- Reads embed `reporter: {id, name}`; `changes` diffs record reporter changes;
  SLQ gains `reporter` (email | `me` | `none`, same ops as `assignee`) incl.
  autocomplete; migration `b82af9418040` **backfills reporter from the event log**
  (each item's `item.created` actor).

## 2. SLA policies + timers (`slas` module)

- `sla_policies`: workspace-scoped (optional single-project scope), name, enabled,
  `response_minutes` / `resolution_minutes` (≥1, at least one required),
  `pause_state_names` (state NAMES that stop the clock — e.g. "Waiting for artist").
  CRUD `GET/POST/PATCH/DELETE /sla-policies` — reads for any member, writes gated on
  the new workspace-scoped `Permission.SLA_MANAGE`.
- **Timer math is pure** (`timers.py`, tested in `tests/test_sla.py`): the clock runs
  from item creation, pauses while the item sits in a pause state (intervals from the
  event-log state timeline — `reporting/timeline.build_item_timelines` reused), and
  the deadline is when accumulated ACTIVE time reaches the target. "Met late" is
  recorded as breached-and-met.
- **Response met** = first PUBLIC comment by someone who is neither the reporter nor
  the automation system actor (seam: `comments.public_comment_times`).
  **Resolution met** = first entry into a done-category state.
- **Engine** (`engine.py`): a periodic clock (every `RADD_SLA_CHECK_INTERVAL`, 60s —
  NOT an outbox consumer; breaches happen when nothing changes). Per enabled policy it
  evaluates non-terminal items, stamps `sla_item_states` bookkeeping rows, and emits
  `sla.breached` (entity_type **item**, so it lands in the item's History feed)
  **exactly once** per (item, policy, kind).
- `GET /items/{id}/sla` (`item.read`) recomputes LIVE for display (bookkeeping rows
  only gate event dedup).
- **notify integration**: the notify consumer handles `sla.breached` → `sla_breach`
  notifications to the assignee + watchers (no actor — the engine is a clock).

## 3. Canned responses (`canned` module)

`canned_responses` (workspace_id, title, body, position). Reads for any member
(`item.read` at workspace scope); CRUD gated `workspace.manage`. Emits
`canned_response.created/.updated/.deleted`.

## Frontend

- **Reporter** select in the issue properties rail (defaults server-side).
- **SLA panel** in the rail (only when a policy applies): per-policy timer chips —
  countdown / Paused / Breached / Met / Met late; refreshed every minute + realtime.
- **Canned responses**: "Insert canned response…" select above the comment composer
  (appends the body to the markdown draft); admin page `/settings/canned`.
- **SLA policies** admin page `/settings/sla` (create with scope/targets/pause
  states, enable/disable toggle, delete).
- Inbox renders `sla_breach` rows (timer icon, "SLA response target breached (…)").

## Known simplifications

- `Permission.SLA_MANAGE` is workspace-scoped → admins only (same shape as
  `CYCLE_MANAGE`/`AUTOMATION_MANAGE`).
- SLA targets are wall-clock (no business-hours calendar yet).
- Pause states match by NAME across the whole scope (per-project resolution at
  evaluation; a renamed state silently stops pausing).
- Policies apply per item to EVERY enabled policy in scope (no priority/first-match).
- No per-item SLA chips on boards/lists yet (detail rail only) and no CSAT.
- The engine evaluates all non-terminal items each tick (fine at studio scale; add
  due-time indexing when it bites).
- Automations can't trigger on `sla.breached` (their triggers are item events only) —
  escalation actions come when automation triggers grow.
