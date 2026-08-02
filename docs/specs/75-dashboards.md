# Spec 75 — Composable dashboards

Target-features wave, part 8. User-assembled dashboards of widgets over data
surfaces that ALREADY exist — the reporting endpoints, SLQ counts/lists, view
counts. The server side is deliberately thin: a `dashboards` module owning
layout + sharing (the spec-57 idiom verbatim); every widget FETCHES through the
existing read APIs, so RBAC/visibility filtering is inherited, not reimplemented.

## 1. Data model (`dashboards` module, after views/reporting in RADD_MODULES)

- `dashboards`: id, workspace_id FK, name, description, `owner_id` (creator;
  full control), `workspace_access` ShareLevel|NULL (the views vocabulary),
  position, timestamps.
- `dashboard_shares`: exactly-one-of user_id/team_id + `level`
  (viewer|editor|owner), FK CASCADE — a straight copy of `view_shares`
  semantics incl. validation, `PUT /dashboards/{id}/sharing` full-replace,
  `POST /{id}/transfer`, and the visibility union (owner ∪ grantees ∪
  members when workspace_access set; non-visible → 404, admins included).
- `dashboard_widgets`: id, dashboard_id FK CASCADE ix, position,
  `widget_type` StrEnum, `title` (nullable override), `width` int 1..3 (grid
  thirds), `config` JSONB validated PER TYPE on write (409/422):
  - `report_throughput|report_cfd|report_time_in_state` — {project_id,
    interval?/kind?}
  - `report_velocity` — {workspace_id, last?, measure?}
  - `report_burnup` — {cycle_id, measure?}
  - `report_sla` — {workspace_id, project_id?, weeks?}
  - `slq_count` — {workspace_id, project_id?, q, label?} (q compile-validated
    against the scope registry → 422 {detail, position})
  - `slq_list` — {workspace_id, project_id?, q, limit<=20}
  - `view_count` — {view_id} (view must be visible to the WRITER; per-viewer
    visibility applies at render through /views/counts)
- Widget CRUD: `POST/PATCH/DELETE /dashboards/{id}/widgets[/{wid}]` +
  reorder via position patch — owner/editor gated. Dashboard CRUD mirrors
  views (`create` = item.read member floor; workspace_access broadcast needs
  `view.create` — reuse the same broadcast atom rather than minting a new
  one... decided: new `DASHBOARD_*` CRUD atoms via the spec-50 ResourceSpec
  registry, global scope, umbrella `workspace.manage`, so roles matrices
  stay uniform; the broadcast gate is `dashboard.create`).
- Events: `dashboard.created/.updated/.deleted` (+ share_count payload on
  sharing changes).

## 2. Rendering contract (frontend does the fetching)

- `GET /dashboards?workspace_id=` (visibility-filtered) + `GET /dashboards/
  {id}` → definition incl. widgets + per-actor `can_edit`/`can_manage`.
- Each widget maps to an EXISTING query: reports → `/reports/*`, slq_count →
  a `/items/ids`-style count (add `GET /items/count?…&q=` — trivial, same
  filter path, returns {total}), slq_list → `/items?q=&limit=`, view_count →
  `POST /views/counts`. A viewer who lacks read on a widget's scope gets the
  endpoint's own 403/404 → the widget renders an "unavailable" card; the
  dashboard never errors as a whole.

## 3. Frontend

- Sidebar "Dashboards" section (collapsible, like Queues): visible dashboards
  + "New dashboard".
- `/dashboards/$dashboardId`: CSS-grid (3 columns, widget width 1–3, auto
  rows); widget cards reuse the exact chart components from the reports pages
  (extracted where needed into `components/reports/*` shared renderers);
  slq_list renders compact item rows (key, title, state chip → peek).
- Edit mode (owner/editor): "Add widget" modal — type picker → config form
  (project/cycle/view pickers, SLQ input with live validation, measure
  toggle); per-widget menu: edit, width 1/2/3, move up/down, remove. Title
  header: rename, sharing dialog (the ViewModal sharing UI generalized),
  delete.
- Refresh: widgets are ordinary queries (entity-tagged) — realtime item
  invalidations keep counts live for free; report widgets refetch on mount /
  60s stale time.

## 4. Tests

- sharing/visibility parity with views (visible set, 404 for outsiders,
  editor vs owner rights, transfer).
- widget config validation: bad SLQ 422 w/ position; view_count on a view
  the writer can't see 409; width bounds.

## Known simplifications

- No drag-grid persistence (position + width only); no auto-refresh interval
  config; no dashboard-level TV mode yet.
- slq_count issues one count query per widget per render — fine at this
  scale; batch later if dashboards grow.

## As-built notes

Shipped as specced — new `dashboards` module (appended last in RADD_MODULES;
deps events/workspace/auth/teams/items/cycles/views/reporting). Backend:

- Tables per spec (models.py): `dashboards` (owner_id, workspace_access
  ShareLevel|NULL, description, position), `dashboard_shares` (exactly-one-of
  user/team DB CHECK `ck_dashboard_shares_one_subject` — the item_participants
  idiom — unique per (dashboard, subject), FK CASCADE), `dashboard_widgets`
  (widget_type, nullable title, width 1..3, position, config JSONB). Migration
  `9176930be113` (from `7a1827897d5c`; the spurious `ix_doc_pages_fts`
  autogen noise deleted from both directions), applied.
- Sharing (service.py) is views/service.py's spec-57 code adapted 1:1
  (`_grant_level`/`_load_visible`/`require_edit`/`_require_manage`/
  `_validate_shares`/`update_sharing`/`transfer_ownership`) with ONE
  deliberate omission: no legacy owner-less branch — every dashboard has an
  owner from birth, so there is no view.update-atom fallback. ShareLevel is
  re-exported from views.types (one vocabulary, one wire format). Broadcast
  gate = the new `dashboard.create` atom; personal floor = item.read at
  workspace scope. Transfer keeps the previous owner as an editor grantee.
  User-merge inventory extended (`dashboards.owner_id` repoint +
  `dashboard_shares` dedupe).
- RBAC: `dashboard` ResourceSpec in auth/types.py CRUD_RESOURCES (GLOBAL
  scope, umbrella `workspace.manage` DIRECTLY — the member/issue_type
  precedent; no dashboard.manage coarse verb). DEVIATION from the letter of
  §1: the builtin admin role definition now carries the three atoms as
  global-scoped riders (the doc.write-on-member precedent) so the migration's
  JSONB-append backfill keeps stored rows identical to the seed — display-only
  either way, since global-scope checks key on workspace membership;
  test_authz's builtin-admin assertion updated accordingly.
- Widgets (widgets.py + schemas.py): create bodies are a pydantic
  discriminated union on `widget_type` (the automations Action idiom) so
  unknown types / wrong config shapes 422 at the boundary; PATCH configs
  revalidate against the STORED type (`WidgetConfigError` → 422 via the module
  handler; widget_type immutable — remove + re-add to change kinds). Semantic
  pass: SLQ via `items.validate_slq` (SlqError → 422 {detail, position});
  project/cycle/view references must exist, live in the dashboard's
  workspace, and be readable/visible to the WRITER → 409. View visibility
  checks go through a new public views seam `views.service.visible_view`.
  Widget writes are edit-gated, return the full DashboardRead, and emit
  `dashboard.updated`.
- `GET /items/count` (items router, before the parameterized routes): same
  filter surface + visibility as /items/ids, `{total}` only — both now share
  the factored `_visible_ids_query` builder in items/bulk.py.

Frontend:

- The reports pages' chart cards were ALREADY extracted to
  `components/reports/*` — reused directly; they grew pin props for widget
  configs (TimeInStateCard `initialKind`, VelocityCard `initialLast`/
  `initialMeasure`, BurnupCard `fixedCycleId` [hides the picker] /
  `initialMeasure`, SlaCard `initialWeeks`; ThroughputCard/CumulativeFlowCard
  already took everything as props). `isoDaysAgo` moved to lib/dates.ts.
  Report queries got `staleTime: REPORT_STALE_MS` (60s) — reports pages
  included.
- routes/dashboard.tsx: 3-column grid (widths as literal lg:col-span
  classes), hover toolbar per widget (edit / width-cycle / move up-down as a
  position swap / remove), Add-widget modal (WidgetModal: type picker +
  per-type form, SLQ input = the ordinary SlqEditor + useSlqValidation),
  header Edit/Share/Delete gated on can_edit/can_manage. slq_count and
  view_count render big-number cards, slq_list compact peek rows; any
  403/404'd fetch (or a server-omitted view count) renders the Unavailable
  card. Sharing dialog reuses `ViewSharingEditor` verbatim via a new `noun`
  prop ("dashboard"); transfer applies last, after the sharing PUT.
- Sidebar: collapsible Dashboards section (the Queues idiom) with a New
  dashboard row (create modal = name only; description on edit). New
  Entity.dashboard cache tag + `dashboard` in realtime's SERVER_ENTITY_TAGS;
  count/list widgets are Entity.item-tagged so realtime keeps them live.

Tests: `tests/test_dashboards.py` (4 — sharing matrix incl. admin-404 +
broadcast floor, transfer, widget validation incl. cross-workspace 409 and
PATCH-shape 422, /items/count ↔ /items/ids parity under visibility); suite
766 green.
