# Spec 63 — SLA depth: business hours, priority tiers, visibility, reporting

Service-desk wave, part 3. Spec 30's known simplifications come due: SLA
policies gain business-hours windows and per-priority targets with first-match
resolution, timers become visible on lists/boards, and reporting gets a
service-desk section.

## 1. Policy model additions (`sla_policies`)

- `priorities` JSONB list of Priority values, default `[]` = matches every
  priority. "P1 responds in 1h, P3 in 8h" = two policies with different
  filters.
- `position` int (default 0) — resolution order; migration backfills existing
  rows by name order. Admin UI reorders (up/down, same idiom as the config
  editors).
- `business_start_minute` / `business_end_minute` (nullable ints, minutes from
  midnight, 0–1439, both-or-neither, start < end — else 409): on top of
  `work_week_only`, the clock also pauses OUTSIDE the daily window on working
  days. A ticket filed at 23:00 against a 9:00–17:30 window starts burning at
  9:00.

## 2. First-match resolution (SEMANTIC CHANGE, replaces evaluate-all)

- New `service.matched_policy(session, item) -> SlaPolicy | None`: enabled +
  scope-matching policies ordered by (position, created_at); the FIRST whose
  `priorities` filter matches the item's priority wins. Spec 30's "every
  enabled policy applies" is retired — one policy per item, Jira-style
  first-match. Engine, `GET /items/{id}/sla`, and the batch endpoint (§3) all
  route through it (the engine groups items by matched policy, then evaluates
  per policy as before).

## 3. Batch endpoint (list/board chips)

- `POST /items/sla/batch` body `{item_ids: [≤200]}` (item.read enforced by
  filtering to readable items, existing bulk idiom) →
  `{item_id: [{policy_name, kind, due_at, met_at, breached, paused,
  remaining_seconds}]}` — live recompute via the matched policy, same shape the
  rail panel uses.

## 4. Timer math (`timers.py`, pure)

- `business_hours_pauses(start, end, start_minute, end_minute, working_days)`
  → per-day pause intervals covering [midnight, window-open) and
  [window-close, midnight) on working days (non-working days stay whole-day
  pauses when `work_week_only`). Merged into the existing pause list in
  `evaluate_items`; deadline horizon scales with the shrunken active day
  (window minutes per day → days needed × 2 + 14d slack). Unit-tested.

## 5. SLA report (reporting module)

- `GET /reports/sla?workspace_id=&project_id?=&weeks=1..26` (default 12;
  ITEM_READ at workspace scope): weekly buckets over `sla_item_states` joined
  to items (bucketed by item created week) → `{week, items, response_met,
  response_breached, resolution_met, resolution_breached, breach_rate,
  avg_response_seconds, avg_resolution_seconds}` (averages wall-clock from
  met stamps; business-time-adjusted averages are a later refinement).
- Reports page gains a **Service desk** section: summary tiles (breach rate,
  avg first response, avg resolution over the window) + weekly met/breached
  trend, following the page's existing chart idioms.

## Frontend

- SLA settings page: priority multi-select chips, business-hours HH:MM pair,
  drag-free up/down reordering, and a banner explaining first-match.
- List rows + board cards get an **sla** slot in the per-surface card display
  config (DisplayMenu toggle, default OFF): nearest-to-breach chip (reuses
  SlaTimerChip states — countdown/paused/breached/met), fed by one batch call
  per loaded page, refetched every 60s.

## Tests

Business-hours pure math (window clipping, weekend+window merge, target far
beyond a day's window); first-match selection (priority filter, position
order, project scope beats nothing — plain ordering only); batch endpoint
shape + permission filtering; report aggregation smoke.

## Known simplifications

- One policy per item, full stop (complementary response-only + resolution-
  only policy PAIRS no longer stack — fold both targets into one policy).
- Report averages are wall-clock, not business-time.
- No per-policy calendar/timezone: the window is naive UTC like every SLA
  timestamp (the studio runs one timezone).

## As-built notes

- Migration `fb577d3807f9` (chained on `7be36ff1ac2c`): the four columns +
  position backfill by `ROW_NUMBER() OVER (PARTITION BY workspace_id ORDER BY
  name, id) - 1`. Live DB had zero policy rows, so the backfill was a no-op.
- The window pair rule (both-or-neither, start < end) is enforced in the
  service (`ConflictError` → 409, per spec); the 0–1439 range check lives in
  the schemas (422) — a range violation is malformed input, not a conflict.
- `slas/service.py` split: policy CRUD + first-match stay in `service.py`;
  `evaluate_items`/`sync_states`/`terminal_item_ids` + the batch compute moved
  to `slas/evaluation.py` (file-size rule; no external consumers existed).
  `policies_for_item` (evaluate-all) was deleted outright.
- Business window without `work_week_only` applies to EVERY calendar day;
  with it, working days get the window and non-working days stay whole-day
  pauses (`business_hours_pauses` takes `working_days`; callers pass all-week
  when work_week_only is off). Horizon = ceil(target/window) × 2 + 14d for any
  policy with work-week or window pauses.
- `/reports/sla` reads a models-only seam (`slas/report.py`) because
  `slas/service.py` already imports `reporting/timeline.py` — a service-level
  import back the other way would cycle, and reporting cannot declare `slas`
  in depends_on (RADD_MODULES loads reporting first). Buckets fold per ITEM
  first (min met stamp, any breach stamp) so pre-63 evaluate-all rows — one
  item, several policies — do not double-count; `_SlaWeekFold` is the spec-65
  extension point (csat_avg/csat_count).
- Batch endpoint: items without a matched policy (or unreadable/unknown ids)
  are omitted from the response object rather than mapped to `[]`.
- Frontend: the sla slot is wired on the project list, project board, saved
  views (list/board/swimlanes), and planning — planning's sections page
  independently, so each section fires its own batch call. Surfaces slice
  visible ids to the 200-id batch cap; rows past that render no chip until a
  narrower page. The Service-desk report card renders on BOTH the project
  reports page (project-scoped) and workspace reports (workspace-wide).
- The settings-page reorder renumbers the whole list to its displayed order on
  each up/down move (heals legacy position ties) instead of swapping just the
  two neighbours' stored values.
