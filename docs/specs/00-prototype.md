# Prototype build — coordination rules for build agents

Goal: navigable prototype — web UI (login → projects → boards → item detail), teams +
individual assignment, epics, comments, full action RBAC + field-level visibility, Jira
sample importer. Read `CLAUDE.md` (non-negotiable dev rules)
and `docs/modules.md` first.

## Hard rules for every build agent

1. **Touch only the paths your spec assigns you.** Other agents work in other paths concurrently.
2. Backend verification runs on **port 8001** (`uv run uvicorn --factory radd.app:create_app --port 8001`); port 8000 belongs to the supervisor. Postgres is up on localhost:5455 (podman). Kill any server you start when done.
3. **Migrations:** run `uv run alembic heads` first; create exactly ONE new revision chained on the current single head (`alembic revision --autogenerate -m "..."`, review it, `upgrade head`). Never edit existing revisions. If heads shows two heads, stop and report.
4. Follow the module pattern exactly (see existing modules: `types.py` enums first, `models.py`, `schemas.py`, `service.py`, `router.py`, `__init__.py` with `RaddModule`). Register new modules in `config.py` `modules` tuple. No magic strings — StrEnums/dataclasses/Settings.
5. Update `docs/modules.md` (your module's row + any new extension point + known simplifications) in the same change.
6. Verify by RUNNING (curl the endpoints; extend/run the relevant `scripts/demo*.sh`). Fix what you find.
7. When done and verified: `git add` YOUR paths only and commit (message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`). Never `git add -A`.
8. Report back: what you built, what you verified (with real output snippets), known gaps.

## Wave map

- Wave 1: 01-auth-teams (backend) ∥ 04-frontend phase 1 (web/ only) ∥ Jira sample data (research only)
- Wave 2: 02-items-expansion (backend) ∥ 04-frontend phase 2 (web/ only)
- Wave 3: 03-rbac-field-visibility (backend) ∥ 04-frontend phase 3 + 05-importer script
- Wave 4: supervisor integration + end-to-end walkthrough
