# Spec 06 — roles as data + permission engine + membership management (backend)

Allowed paths: `server/src/radd/modules/auth/` , `server/src/radd/modules/teams/`,
`server/src/radd/modules/workspace/` (ProjectRead permissions hydration only),
`server/src/radd/seed.py`, `server/migrations/versions/` (one revision), `server/tests/`,
`server/scripts/demo.sh` (extend with a roles scene), `docs/modules.md`.
Do NOT touch `items/`, `comments/`, `fields/`, `views` or `web/` — other agents own them.

## Roles as data

New tables (auth module owns roles):
- `roles`: id, workspace_id FK, key (slug, unique per workspace), name, description default "",
  permissions JSONB (list of Permission values), is_builtin bool, position int, timestamps.
- Builtins seeded per workspace (extend the existing project-created-style hook pattern — a hook
  on `workspace.created`, plus migration backfill for existing workspaces), from a
  `BUILTIN_ROLES` dataclass tuple in `auth/types.py`:
  - `admin`: every project-scoped permission (incl. project.manage, view.manage, comment.read_internal)
  - `member`: item.read/create/update, comment.write, comment.read_internal, view.manage
  - `viewer`: item.read
  Builtin rows: is_builtin=True; PATCH allowed only for `permissions` of NON-builtin roles;
  builtin permission sets are immutable (409). DELETE only non-builtin AND unreferenced (409 otherwise).
- `Permission` enum gains: `view.manage`, `comment.read_internal`, `role.manage` (workspace-scoped,
  granted implicitly to workspace admins like workspace.manage).

## Membership model

- `project_members`: project_id + user_id pk, role_id FK roles. Endpoints:
  `GET/POST /api/v1/projects/{id}/members` {user_id, role_id}, `PATCH .../members/{user_id}`
  {role_id}, `DELETE .../members/{user_id}` — require project.manage.
- `project_teams`: replace `role` string column with `role_id` FK (migration maps
  'admin'/'member'/'viewer' strings to that workspace's builtin role ids). Add
  `PATCH /projects/{project_id}/teams/{team_id}` {role_id} and `DELETE` (detach).
- Workspace membership: add `PATCH /workspaces/{id}/members/{user_id}` {role} and `DELETE`
  (workspace.manage). Keep WorkspaceRole enum (admin|member) — workspace role stays a simple enum;
  data-driven roles apply at project scope.

## Engine refactor (`auth/authz.py`)

- `effective_permissions(session, user, *, project=None, workspace_id=None) -> frozenset[Permission]`:
  instance admin or that workspace's admin → ALL permissions. Else union of: direct
  `project_members` role permissions; `project_teams` role permissions for the user's teams;
  workspace member → the workspace's builtin `viewer` role permissions as floor. Workspace-scoped
  checks (no project): workspace admin → all; member → floor set.
- `require(...)` keeps its signature but checks membership of the permission in the union;
  returns the frozenset (callers that used the returned role must be updated — grep for uses).
- Keep a compatibility helper `subjects_for(session, user, project) -> {role_ids: set, team_ids: set}`
  exported for the fields-permission agent (spec 07) to consume later.
- `GET /api/v1/permissions` → catalog: `[{key, description, scope: project|workspace}]` from the
  enum + a PERMISSION_DESCRIPTIONS dict (for the admin matrix UI).
- Roles CRUD: `GET/POST/PATCH/DELETE /api/v1/roles?workspace_id=` (role.manage; GET for any member).
- `ProjectRead` gains `permissions: list[str]` for the CURRENT user (hydrate in workspace router
  via authz; keep it one batched call per request). `/auth/me` workspaces entries gain
  `permissions` (workspace-scope union).

## Migration notes

One revision: create roles + project_members; backfill builtin roles for every existing workspace;
convert project_teams.role → role_id; drop old column. `min_read_role/min_write_role` on
field_definitions are spec 07's problem — do not touch fields tables.

## Tests (mandated — this is the core seam)

Rework/extend `server/tests/test_authz.py`: builtin sets, union across direct+team+floor,
workspace-admin override, custom role grants exactly its permissions, require() 403 paths,
immutable builtins. Target ≥ existing 19 passing.

## Verify

demo.sh roles scene: create custom role "triager" (item.read + item.update + comment.write),
assign a user directly to the TD project with it, show they can update an item but NOT create one
(403), list `GET /roles`, show ProjectRead.permissions for that user. Full demo.sh +
demo_webhooks.sh green (`API=... uv run` etc. — verify on port 8001, never touch 8000, kill by exact PID).
`uv run alembic upgrade heads` (plural — another agent may create a sibling head in parallel;
a merge revision is the supervisor's job). Commit with explicit pathspecs only.
