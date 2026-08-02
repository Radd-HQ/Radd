# Spec 08 — saved views (custom boards) + richer item filters (backend)

Allowed paths: `server/src/radd/modules/views/` (new module), `server/src/radd/modules/items/`
(router+service filter additions — YOU own items/ this wave), `server/src/radd/config.py`
(modules tuple), `server/migrations/versions/` (one revision), `server/scripts/demo_views.sh`
(new file), `docs/modules.md`.

May run in parallel with spec 06 (which owns auth/teams/workspace). If `Permission.VIEW_MANAGE`
doesn't exist yet when you wire permissions, use `Permission.ITEM_READ` for personal views and
`PROJECT_MANAGE` for shared views with a `TODO(spec-06)` comment — the supervisor reconciles.
Use `alembic upgrade heads` (plural); a sibling head from spec 06 is expected — do NOT merge
heads yourself.

## Item filter extensions (`GET /api/v1/items`)

- Existing single-value params stay; add repeatable/multi where listed:
  `state_id` (repeatable), `category` (repeatable), `kind` (repeatable), `priority` (repeatable),
  `assignee_id` (repeatable, accept literal `none` for unassigned), `team_id` (repeatable, `none`),
  `label` (repeatable label NAME — join through item_labels/labels),
  `cf` (repeatable, format `key:value` — equality on custom_fields; for multi_select fields match
  containment; parse errors → 422 with clear message).
- Implementation: keep it in items service; JSONB containment (`custom_fields @> {...}`) for cf
  equality where possible; document performance note in modules.md (expression indexes later via
  the registry's `indexed` flag).

## views module (new)

- Table `views`: id, workspace_id FK, project_id FK nullable (null = workspace-spanning),
  name (≤100), view_type (`ViewType` StrEnum: board|list), filters JSONB (validated by a
  pydantic `ViewFilters` model mirroring the query params above: states, categories, kinds,
  priorities, assignees, teams, labels, custom_fields dict), group_by (`GroupBy` StrEnum:
  state|assignee|priority|kind|team), owner_id FK users nullable (**null = shared with the
  workspace**), position int, timestamps.
- Endpoints: `GET /api/v1/views?workspace_id=&project_id=` (shared + own personal, ordered by
  position then name), `POST` (personal: any item.read holder; shared (owner null): view.manage —
  see fallback note above), `PATCH /views/{id}` (owner, or view.manage for shared), `DELETE`
  (same rule). Events: `view.created/.updated/.deleted`.
- `filters` must round-trip exactly to the item query params so the frontend can compose
  `GET /items` from a view with zero translation logic — document the mapping in modules.md.

## Verify

`demo_views.sh`: create labels/items spanning two states with cf values; create a shared board
view "FX urgent" (filters: label + cf show + category, group_by state) and a personal list view;
show `GET /items` with the composed params returns exactly the filtered set (incl. `cf=show:RUX`,
`label=urgent`, `assignee_id=none`); non-owner cannot PATCH another user's personal view (404/403).
demo.sh + demo_webhooks.sh regression green. Port 8001 only for your own server; never touch 8000;
kill exact PIDs; commit with explicit pathspecs.
