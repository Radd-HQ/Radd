# Spec 14 — cycles + releases + item planning fields (backend foundation)

The foundation the other feature waves build on: iterations (cycles), releases, and the
item planning attributes (dates + dependency links) that roadmap/Gantt and reporting need.

Allowed paths: `server/src/radd/modules/cycles/` (new), `server/src/radd/modules/releases/` (new),
`server/src/radd/modules/items/` (columns, links, SLQ, hydration), `server/src/radd/config.py`
(modules tuple), `server/migrations/versions/` (ONE revision on the current single head),
`server/tests/test_slq.py` (extend for new SLQ fields), `server/scripts/demo_planning.sh` (new),
`docs/modules.md`. Do NOT touch web/, auth/, or other modules' internals — call their services.

Single alembic head currently `6afdeaf4f62d`; keep ONE head. Never touch port 8000 (verify on
8001/8002, kill exact PIDs). Seeded admin hussein@hjarrar.com / change-me; live TD/DEV data must
survive (all new columns nullable, all new tables additive). Commit with explicit pathspecs.

## cycles module (workspace-level iterations — spans projects, like the studio's PIPE sprints)

- `cycles`: id, workspace_id FK, name, start_date (Date), end_date (Date), goal (Text, default ""),
  timestamps. `CycleStatus` is DERIVED (not stored): upcoming (today < start), active
  (start ≤ today ≤ end), completed (today > end) — expose as `status` on reads; compute with a
  DB-independent "today" passed in (accept `date.today()` at the service boundary — tests inject).
- Endpoints: `GET /cycles?workspace_id=[&status=active]`, `POST` (workspace member+ with
  `project.create`-level? no — gate on a new `Permission.CYCLE_MANAGE`; add it to authz's
  workspace-admin set + builtin admin/member roles so members can run sprints), `GET/PATCH/DELETE
  /cycles/{id}`. Events `cycle.created/.updated/.deleted` (payload: name, start_date, end_date).
- Validation: end_date ≥ start_date (409 otherwise). Deleting a cycle nulls items' cycle_id
  (ON DELETE SET NULL on the FK).
- Service helpers others import: `get_cycle`, `cycles_by_ids`, `active_cycles(workspace_id, today)`.

## releases module (project-scoped, automation-writable — replaces the CI-writes-labels hack)

- `releases`: id, project_id FK, name, version (String, e.g. "BNX.2.3"), status
  (`ReleaseStatus` StrEnum: planned|released, default planned), released_at (DateTime nullable),
  description (Text default ""), timestamps. Unique(project_id, version).
- Endpoints: `GET /releases?project_id=`, `POST`/`GET`/`PATCH`/`DELETE /releases/{id}`, gated on
  `Permission.PROJECT_MANAGE` (create/edit) and `ITEM_READ` (list). Setting status→released stamps
  released_at server-side. Events `release.created/.updated/.deleted`.
- The point of "automation-writable": these are ordinary API resources a service-account/PAT (CI)
  or the automations engine (spec 15) can POST to and assign — no special path. Note that in docs.
- Helpers: `get_release`, `releases_by_ids`, `resolve_release(project_id, version)` (find-or-none).

## items expansion

- `work_items` += `start_date` (Date null), `target_date` (Date null), `cycle_id` (FK cycles
  ON DELETE SET NULL, null), `release_id` (FK releases ON DELETE SET NULL, null).
- New table `item_links`: id, source_item_id FK work_items CASCADE, target_item_id FK CASCADE,
  `link_type` (`ItemLinkType` StrEnum: blocks | relates | duplicates), unique(source, target,
  link_type). Rules (service, 409 on violation): no self-link; both items same project; no exact
  duplicate; `blocks`/`duplicates` are directional, `relates` symmetric (reject the mirror dup).
- Schemas: ItemCreate/ItemUpdate gain start_date, target_date, cycle_id, release_id (nullable;
  omitted = unchanged, explicit null = clear — use the existing `model_fields_set` idiom).
  Validation: cycle in same workspace; release in same project; target_date ≥ start_date when both
  set (409).
- ItemRead gains: start_date, target_date, `cycle` ({id, name, status}|null),
  `release` ({id, version, status}|null), and `links`: `{outgoing: [{link_type, item:{id,key,title}}],
  incoming: [...]}` (incoming = rows where this item is the target). Batch-hydrate all of it (no N+1)
  — extend `items/hydration.py`.
- Link endpoints (in items router): `POST /items/{id}/links` {target_id | target_number, link_type},
  `DELETE /items/{id}/links/{link_id}`. RBAC: item.update on the project.

## SLQ additions (extend `items/slq/` catalog + compiler + suggest value sources)

- `cycle` (= name | none | IS [NOT] EMPTY; value source = workspace cycle names + `none`),
  `release` (= version | none | IS [NOT] EMPTY; value source = project release versions),
  `blocks`/`blocked` (IS [NOT] EMPTY = has outgoing/incoming blocks link; and `= <key>` meaning
  links to that item — optional, IS EMPTY is the must-have), `start`/`target` (date comparisons
  + IS [NOT] EMPTY). Register ops in the catalog op-tables, compile to joins/EXISTS, and add value
  sources in `suggest_values.py` (cycle/release names; start/target → date hint). Update
  `test_slq.py` + the suggest tests accordingly.

## Verify (demo_planning.sh, port 8001)

Seed+login; create a cycle (assert derived status), a release; create two items, set dates,
assign one to the cycle + release, link item A blocks item B; `GET` both and show the embedded
cycle/release/links; SLQ `cycle = "<name>" AND target IS NOT EMPTY` returns the assigned one,
`blocks IS NOT EMPTY` returns A, `release = "BNX.2.3"` works; a suggest call in value context for
`cycle` lists the cycle name. Then run the FULL regression: `uv run pytest` (all pass, incl. your
SLQ additions), demo.sh / demo_webhooks.sh / demo_permissions.sh / demo_views.sh green.

Report: migration id, new SLQ fields + their ops, verification output, deviations, gaps.
