# Spec 76 — Board depth: WIP limits, issue templates, epic rollup

Target-features wave, part 9. Three contained upgrades to daily surfaces.

## 1. Board WIP limits (views module)

- `views.wip_limits` — nullable JSONB map `{bucket_key: int>=1}` where
  bucket_key is the STATE ID for state-axis boards (the only axis limits
  apply to). Validated on write: known project states when project-scoped,
  positive ints (422). Editable by whoever can edit the view (spec-57).
- SOFT limits: the board column header renders `n/limit` and turns the
  header count amber at the limit and red above it (+ a tooltip). Nothing
  blocks a drop — WIP is a signal, not a gate (automations can enforce via
  a rule on state counts later if ever wanted).
- UI: column-header ⋯ menu → "Set WIP limit…" (number input, clear) — writes
  a PATCH `{wip_limits}` on the view; only shown when the column axis is
  `state` and the actor can edit the view.

## 2. Issue templates (itemtypes module)

- `issue_types.description_template` — nullable TEXT (markdown). Editable in
  the project settings → Issue types editor (a template textarea per type,
  the existing immediate-PATCH idiom; gated issue_type.update).
- New-item modal: when a type with a template is selected and the description
  is EMPTY or still exactly a previously-inserted template, the editor
  prefills with the template (switching types swaps it; user edits stick).
  Served on `IssueTypeRead.description_template` — no new endpoint.

## 3. Epic progress rollup (items module)

- `POST /items/rollup {item_ids: [<=200]}` (authenticated; ids filtered to
  readable projects like sla/batch) → `{item_id: {total, done, in_progress,
  points_total, points_done, estimate_seconds, logged_seconds}}` computed
  over DIRECT+nested descendants (recursive CTE, one query batch): `done` =
  done/canceled-category states; points from spec 70; estimate/logged via
  the timelogging tables when that module is enabled (else zeros).
- Frontend:
  - `CardSlot.progress` (default ON): epic cards/rows render a slim progress
    bar `done/total` (+ points when the project opts in); the batch POST
    fires only when epic-kind items are on the page (mirror useSlaBatch).
  - Issue view: an "Epic progress" block above the children list on
    epic-kind items (same numbers, bigger bar).

## 4. Tests

- wip_limits validation (unknown state 422 project-scoped, non-positive 422);
  limits survive view PATCH round-trip.
- rollup: nested subtask counted once; done counts by category; points/time
  sums; unreadable child projects excluded.

## Known simplifications

- WIP limits are per-view (two boards over the same states can disagree —
  that's a feature: team boards, personal boards).
- Rollup is on-demand (no denormalized counters); 200-item pages keep it one
  CTE per page.
- Templates are per issue-type, not per project+form; forms remain the
  structured-intake path.

## As-built notes

Shipped as specified; migration `6941ef0ddab2` (from `9176930be113`), tests in
`server/tests/test_board_depth.py` (5), suite 771 green.

- **WIP limits** — `views.wip_limits` nullable JSONB `{state_id: int>=1}`.
  Values ≥1 are pydantic-enforced on `ViewCreate`/`ViewUpdate` (422 via a
  shared `WipLimits` alias); PROJECT-scoped views validate keys against
  `workflow.list_states` (409 `ConflictError`); workspace-spanning views store
  any UUID key untouched — their buckets are state-NAME-keyed, so a limit
  simply never matches (display-only contract from the spec). PATCH clears via
  the `model_fields_set` idiom (explicit null or `{}`). The board column header
  (`ViewBoard`) renders `n/limit` — amber at the limit, red above, tooltip
  "WIP limit N" — and the ⋯ menu (`WipLimitMenu`, DisplayMenu-style popover
  with number input + Clear) appears only when axis==state ∧ `view.can_edit` ∧
  the view is project-scoped (name-keyed workspace buckets can't be addressed
  by id, so the editor is withheld rather than offering a write that 422s).
  Swimlane column headers don't carry the menu/count coloring (the plain
  column board is the WIP surface); the count colors against the LOADED page
  (soft signal — pagination can undercount, never overcount limits).
- **Issue templates** — `issue_types.description_template` nullable TEXT
  (pydantic cap 20k), rides the existing issue_type PATCH (`model_fields_set`
  clear, `''`→NULL). Issue-types settings page: a per-type collapsed
  "Template" button expands a markdown textarea (explicit Save/Remove PATCH —
  deliberately NOT the per-keystroke immediate-PATCH used for color; a
  textarea would spam PATCHes). New-item modal: prefill fires when the
  selected type has a template and the draft is PRISTINE (empty or exactly the
  last-inserted template, tracked in state); switching to a template-less type
  while pristine swaps back to empty; the uncontrolled RichEditor is reseeded
  via a `key` bump.
- **Rollup** — `POST /items/rollup` (`items/rollup.py`) built as the
  iterative id-frontier variant (not a SQL CTE): one `parent_id IN (frontier)`
  query per depth level over the whole batch — the epic←issue←subtask
  hierarchy caps this at 3 waves — then one states-category lookup. Children
  inherit their parent's requested-root set, and per-root seen-sets count each
  descendant once even when requested items nest (an epic and its child issue
  both on the page roll up independently and correctly). `done` =
  done+canceled categories; archived descendants still count (the spec says
  ALL descendants). Time comes from new timelogging batch seams
  (`estimate_seconds_by_items`/`logged_seconds_by_items`) behind a deferred
  try/ImportError (the approvals-consume idiom) — zeros when the module is
  absent. Readable requested ids ALWAYS appear in the response (zeros =
  childless), unreadable/unknown ids are omitted (sla/batch shape).
- **Frontend rollup** — `CardSlot.progress` default ON in the board+list
  presets (planning/queue untouched); `useRollupBatch(epicIds, enabled)`
  mirrors `useSlaBatch` (no re-poll interval — invalidation rides
  `entityMeta(Entity.item)` since progress only moves with item writes).
  `RollupRowBar` renders a slim two-tone bar (done emerald / in-progress
  indigo) + `done/total`, nothing for childless epics; threaded through
  ViewBoard, ViewList rows, and ViewSwimlanes cards. Issue view: "Epic
  progress" section above Dependencies with the bigger bar, done/in-progress
  counts, and points when `usePointsEnabled` says the project opted in.
