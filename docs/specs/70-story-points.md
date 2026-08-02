# Spec 70 — Story points (optional, per-project)

Target-features wave, part 3. A points estimation axis alongside time tracking.
HARD REQUIREMENT: fully optional — a project that hasn't opted in shows ZERO
points UI anywhere; reports keep their current item-count semantics by default.

## 1. Opt-in (scoped setting, spec-50 cascade)

- New `SettingKey.ESTIMATION_POINTS` (BOOL, scopes instance/project, config
  default `estimation_points = False`). Project settings → General gains an
  "Story points" toggle (same ScopedSettingsEditor idiom as CSAT/transition
  mode). Resolved per project; the SPA reads it via the project-scoped
  settings it already fetches (or `resolve` exposed on ProjectRead — decide at
  build: cheapest is including resolved key in the existing scoped-settings
  GET the settings pages use, plus a tiny `usePointsEnabled(project)` hook).

## 2. Data + API

- `work_items.estimate_points` — nullable NUMERIC(6,1) core column (like
  `rank`, it's a core sort/filter attribute; owning-module purity yields to
  SLQ/order needs, same call as `flagged`). On `ItemCreate`/`ItemUpdate`
  (nullable, `model_fields_set` idiom; values 0–999, one decimal). Always
  serialized on `ItemRead` (a null field when unused — UI gating is the
  optionality contract, not schema surgery).
- SLQ: numeric field `points` (comparisons, `IS EMPTY`, ORDER BY) wired like
  the existing numeric custom-field paths; suggest includes it.

## 3. Reports in points

- `GET /reports/velocity` and `/reports/burnup` gain `?measure=count|points`
  (default `count`, exact current behavior). `points` sums `estimate_points`
  (null = 0) over the same item sets: velocity per completed cycle, burnup
  scope/completed series. Response rows keep their shape (`completed`/`scope`
  become point sums under the flag).
- `GET /cycles/{id}/stats` adds `points_total`/`points_done` (done = items in
  done-category states) — always computed (cheap same-query sums); UI shows
  the chip only when the project/setting context enables it (workspace cycle
  page shows it when ANY member project opts in — the stats endpooint already
  aggregates cross-project).

## 4. Frontend (all gated on the setting)

- Issue rail: "Points" number field (screen-driven `renderField` case,
  builtin key `points`, secondary placement default) — only rendered when the
  item's project has points enabled.
- Card/List chip: new `CardSlot.points` (default OFF like `sla`) — a small
  `Np` chip on cards/rows via `CardSlots`.
- Board column headers: when the column axis is `state` and the project has
  points on, the header count gains `· Σp` (sum of visible cards' points).
- Reports pages (project + workspace): a Count/Points segmented toggle on the
  velocity + burnup cards, passing `measure=` through.
- Cycle handle chips: points chip appears when nonzero.
- New-item modal: points input shown when the target project opts in.

## 5. Tests

- SLQ `points > 3` / `points IS EMPTY` compile + filter; ORDER BY points.
- velocity/burnup `measure=points` sums vs count parity on a seeded cycle.
- validation bounds (negative / >999 → 422).

## Known simplifications

- Points at report time are CURRENT values (no as-of-completion snapshot) —
  same simplification velocity already makes for assignment.
- No fibonacci/estimate-scale enforcement — any 0–999 with one decimal.
- Instance-level default exists in the cascade so a points-first org can flip
  it once; per-project override still wins.

## As-built notes

Shipped as specced; migration `d8402cfe3773`, 6 tests in `tests/test_points.py`
(SLQ filter/EMPTY/ORDER BY, velocity+burnup measure parity on a seeded
completed cycle, pydantic bounds, cycle-stats sums incl. filters).

- **Resolved-setting read**: went with a dedicated endpoint rather than
  piggybacking ProjectRead — `GET /scoped-settings/resolve?key=&project_id=`
  (any member; item.read on the project when given) returns `{key, value}`
  through `settings.service.resolve`. The SPA's `usePointsEnabled(projectId?)`
  hook wraps it (`resolvedSettingQuery`, 60s stale); omitting `projectId`
  resolves the instance default — the workspace Reports page and
  workspace-spanning views use that, so "ANY member project opts in" for
  cross-project surfaces was simplified to the instance-resolved value.
- **Column**: `work_items.estimate_points NUMERIC(6,1)` with `asdecimal=False`
  so plain floats flow through hydration/events (no Decimal-to-str JSON edge).
  One-decimal quantization is the DB's rounding; the API validates bounds only.
- **Reports**: `ReportMeasure` StrEnum; `VelocityRow.completed` and
  `BurnupPoint.scope/completed` widened to `int | float` — count mode still
  serializes ints (exact prior shape), points mode one-decimal sums.
- **Screens**: `ScreenBuiltinField.POINTS` appended to the arrangeable order
  with a SECONDARY default (`SECONDARY_DEFAULT_BUILTINS`) so the rail field
  lands under "More fields"; `renderField` mounts it only when the project
  resolves points on.
- **SLQ**: `points` = RANGE + IS EMPTY + sortable; null placement follows
  Postgres (ASC nulls last, DESC first), same as custom-field number sorts.
- **Cards**: `CardSlot.points` default OFF everywhere; the `Np` chip renders
  only on items carrying a value, so never-opted-in projects show nothing even
  if the slot is toggled. Board column headers show `· Σ N pts` when the
  column axis is state and points resolve on (plain board; swimlane cell
  headers skipped).
- **History**: `changes.py` records a `points` diff row on updates.
- Deliberately NOT done: cycle-handle/cycle-page points chips (spec §4 line 5 —
  stats carry `points_total/points_done`, UI chip deferred), bulk-edit points,
  and points in `ItemBulkPatch`/builtin field-rule maps (not restrictable).
