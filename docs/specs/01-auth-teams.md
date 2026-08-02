# Spec 01 — auth + teams modules (backend, Wave 1)

Allowed paths: `server/src/radd/modules/auth/`, `server/src/radd/modules/teams/`,
`server/src/radd/modules/events/` (actor column only), `server/src/radd/config.py`
(modules tuple + auth settings), `server/src/radd/exceptions.py` (new error types),
`server/src/radd/app.py` (handlers for new core errors only), `server/migrations/versions/`
(one new revision), `server/pyproject.toml` (deps), `server/src/radd/seed.py`, `docs/modules.md`.

## auth module

Deps to add: `pwdlib[argon2]`.

**Models**
- `users`: id UUID, email (unique, lowercase), name, password_hash (nullable — future SSO users), instance_role str, active bool default true, timestamps.
- `sessions`: id UUID, user_id FK, token_hash (sha256 hex, unique), expires_at, created_at. Settings: `session_ttl_hours: int = 720`, cookie name constant `radd_session`.
- `api_tokens`: id UUID, user_id FK, name, token_hash (sha256 hex, unique), prefix_display (first 12 chars for UI), expires_at nullable, last_used_at nullable, created_at. Token format: `radd_pat_` + 32 bytes urlsafe. Store ONLY the hash; return full token once at creation.
- `workspace_memberships`: workspace_id FK + user_id FK (composite pk), role str.

**Enums** (`types.py`): `InstanceRole(admin|member)`, `WorkspaceRole(admin|member)`,
`AuthEvent(user.created, user.updated)`, `AuthEntity(user, session, api_token)`.

**Endpoints** (contract is FROZEN — frontend builds against it)
- `POST /api/v1/auth/login` {email, password} → 204, sets `radd_session` HttpOnly cookie (SameSite=Lax; `secure` off in dev via setting). 401 on bad credentials (uniform message).
- `POST /api/v1/auth/logout` → 204, deletes session row + cookie.
- `GET /api/v1/auth/me` → `{id, email, name, instance_role, workspaces: [{workspace_id, role}]}`. 401 if anonymous.
- `POST /api/v1/users` {email, name, password, instance_role?} → UserRead (201). `GET /api/v1/users` → list (id, email, name, instance_role, active).
- `POST /api/v1/tokens` {name, expires_at?} → {token (once!), id, name, prefix_display, expires_at}. `GET /api/v1/tokens` → list (no token). `DELETE /api/v1/tokens/{id}` → 204.
- Workspace membership: `POST /api/v1/workspaces/{id}/members` {user_id, role}, `GET .../members`. (Add to auth router, not workspace module.)

**Dependency** (`deps.py`): `current_user(request, session) -> User` — resolves session cookie
OR `Authorization: Bearer radd_pat_...` (update `last_used_at`, throttled to 1/min). Raises
`UnauthorizedError` → 401 handler (core exceptions). Export `CurrentUser = Annotated[User, Depends(current_user)]`
and `OptionalUser`. **Do NOT add auth requirements to other modules' routers yet** (Wave 3 does that) —
only /auth/me, /users, /tokens, /members require it now (users/members require instance or workspace admin).

Passwords: argon2id via pwdlib. Constant-time comparisons. Uniform 401s.

**events**: add `actor_id UUID | None` column to `events` + `actor_id` kwarg on `emit()`
(default None). Include in EventRead. Don't thread it through other services yet.

**Seed** (`radd/seed.py`, run `uv run python -m radd.seed`): idempotent; env or args
`--email --password --name`; creates instance-admin user + workspace `slug=main, name="Main"`
(reuse if exists) + admin membership. Prints what it did.

## teams module

- `teams`: id, workspace_id FK, name (unique per workspace), timestamps. `team_members`: team_id + user_id composite pk.
- `project_teams`: project_id + team_id composite pk, role str (`ProjectRole` values: admin|member|viewer — define `ProjectRole` enum HERE in teams.types for now; spec 03 consumes it).
- Events: `team.created`, `team.updated`, membership changes as `team.updated`.
- Endpoints: `POST/GET /api/v1/teams` (?workspace_id=), `POST /api/v1/teams/{id}/members` {user_id}, `DELETE /api/v1/teams/{id}/members/{user_id}`, `GET /api/v1/teams/{id}/members`, `POST /api/v1/projects/{project_id}/teams` {team_id, role} + `GET` (add in teams router with that path).
- Service helpers others will import: `teams_for_user(session, user_id, workspace_id) -> list[Team]`, `team_project_roles(session, user_id, project_id) -> list[str]`, `get_team`, `teams_by_ids`.

## Verify before committing

Seed admin → login (cookie jar) → /auth/me → create user → create PAT → call /auth/me with
Bearer PAT → create team, add member, attach team to a project. Show real curl output in your report.
