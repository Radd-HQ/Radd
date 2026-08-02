# Spec 03 — full RBAC + field-level visibility (backend, Wave 3)

Allowed paths: `server/src/radd/modules/auth/` (authz.py, deps), `server/src/radd/modules/fields/`,
ALL module routers/services (adding enforcement only), `server/src/radd/exceptions.py`
(ForbiddenError), `server/src/radd/app.py` (403 handler), `server/migrations/versions/` (one
revision), `server/scripts/demo.sh` + `demo_webhooks.sh` (login first), `docs/modules.md`.

## Action RBAC

- `auth/authz.py`: `Permission(StrEnum)` — one member per action class:
  `workspace.manage`, `project.create`, `project.manage` (states/fields/labels/webhooks/teams-attach),
  `item.read`, `item.create`, `item.update`, `comment.write`, `team.manage`, `user.manage`,
  `import.run`. Role→permission map as module-level dataclass/frozenset constants:
  - ProjectRole.VIEWER: item.read
  - ProjectRole.MEMBER: viewer + item.create, item.update, comment.write
  - ProjectRole.ADMIN: member + project.manage
  - WorkspaceRole.ADMIN: everything workspace-scoped incl. project.create, team.manage; InstanceRole.ADMIN: everything.
- `effective_project_role(session, user, project) -> ProjectRole | None`:
  instance/workspace admin → ADMIN; else max(direct `project_teams` roles via user's teams);
  else workspace member → VIEWER (open-visibility default; document). Import ProjectRole from teams.types.
- `require(session, user, permission, *, workspace_id=None, project=None)` raises
  `ForbiddenError` → 403 handler in app.py. Single enforcement seam, unit-test THIS module
  (core invariant many modules rely on — the one place tests are warranted per CLAUDE.md):
  `server/tests/test_authz.py`, runnable `uv run pytest`, pure functions where possible.

## Enforcement wiring

Every router: add `CurrentUser` dependency; resolve scope; call `require(...)`. Items/comments
resolve project from the item. Events list: workspace member+. Webhooks: project.manage-level
(workspace admin). Users/tokens: as spec 01. Anonymous → 401 everywhere except /auth/login, /docs, /openapi.json.
Thread `actor_id=user.id` into every `events.emit()` call (services accept an `actor` param).

## Field-level visibility

- `field_definitions` += `min_read_role` str default viewer, `min_write_role` str default member
  (ProjectRole values; migration backfills defaults).
- fields service: `readable(defs, role)`, `writable_check(defs, values, role)` →
  `FieldValidationError` with "no permission" messages (403-worthy → raise ForbiddenError listing keys).
- items service: `_to_read`/`_hydrate` take the actor's effective role per project and FILTER
  `custom_fields` to readable keys; create/update run `writable_check` before validation.
  Event payloads keep FULL custom_fields (stream consumers are trusted; note in modules.md).
- OpenAPI augmentor: include `x-min-read-role`/`x-min-write-role` per property.
- fields router: creating/updating definitions = project.manage / workspace admin.

## Demo scripts

Update demo.sh + demo_webhooks.sh: run `uv run python -m radd.seed` (idempotent), login with
seeded admin (cookie jar `-c/-b`), pass everywhere. ADD a scene: create a `viewer` user +
membership, a field with `min_read_role: admin` (e.g. `budget_ms`), show admin sees it,
viewer's GET omits it, viewer's write → 403, viewer creating an item → 403.

## Verify

Full demo.sh + demo_webhooks.sh green; `uv run pytest` green; show the viewer-vs-admin output in report.
