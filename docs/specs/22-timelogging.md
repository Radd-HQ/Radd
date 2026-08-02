# Spec 22 — Time logging + timesheets

Per-project time logging (Jira-style estimate + worklogs) and a workspace timesheet
for day/week/month reporting, filterable by team or person, with drill-down into a
specific day, employee, or issue.

## Module: `radd.modules.timelogging`

`depends_on = (events, workspace, auth, teams, items)`. Estimates and worklogs live in
this module's **own** tables so the `items` module never depends on time logging — the
plugin stays per-project-optional. Enabled instance-wide in `RADD_MODULES`; each
project opts in individually.

### Data (`models.py`)

- `project_timelogging` (`project_id` PK, `enabled` bool). **Absence of a row = disabled.**
  The opt-in gate: writes require the row to be `enabled`.
- `work_categories` (`id`, `workspace_id`, `name`, `position`, `archived`, unique
  `(workspace_id, name)`). Workspace-configurable data (like labels/states), seeded per
  workspace, archivable (archived stay on historical worklogs, drop out of the picker).
- `item_estimates` (`item_id` PK, `original_estimate_seconds`). One per item; absence =
  no estimate. Remaining is **derived** (estimate − logged), never stored.
- `worklogs` (`id`, `item_id`, `author_id`, `category_id` nullable SET NULL, `worked_on`
  **Date**, `time_spent_seconds`, `note`). Bucketed by a plain Date — no timezone math
  (sidesteps the reporting-module TZ bucketing flake).

### Durations (`duration.py`)

Jira-style `2w 1d 4h 30m` ⇄ seconds. Bare number = minutes. Working day/week lengths
(`RADD_TIMELOG_HOURS_PER_DAY=8`, `RADD_TIMELOG_DAYS_PER_WEEK=5`) make `1d`/`2w`
convert consistently everywhere. Pure functions (units are arguments), unit-tested
(`tests/test_timelog_duration.py`) — the module's one core invariant. Invalid text
raises `DurationError` → the module maps it to 422 (registered `exception_handler`).

### Endpoints

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/projects/{id}/timelogging` | `item.read` (project) | `{project_id, enabled}` |
| PUT | `/projects/{id}/timelogging` | `project.manage` | enable/disable |
| GET | `/work-categories?workspace_id=[&include_archived=]` | `item.read` (ws) | ordered list |
| POST | `/work-categories` | `workspace.manage` | |
| PATCH | `/work-categories/{id}` | `workspace.manage` | rename / archive |
| POST | `/items/{id}/worklogs` | `worklog.write` + **enabled** | author = current user; `time_spent` is duration text |
| GET | `/items/{id}/timelog` | `item.read` | summary: estimate/logged/remaining + entries |
| PUT | `/items/{id}/estimate` | `item.update` + **enabled** | returns the summary |
| DELETE | `/items/{id}/estimate` | `item.update` | clears; returns the summary |
| PATCH | `/worklogs/{id}` | author + `worklog.write`, or `project.manage` | |
| DELETE | `/worklogs/{id}` | author + `worklog.write`, or `project.manage` | |
| GET | `/timesheet?workspace_id&start&end[&user_id&team_id&project_id]` | `item.read` (ws) | flat entries + total |

Emits `worklog.created` / `worklog.updated` / `worklog.deleted` (payload: item_id,
author_id, worked_on, time_spent_seconds).

### RBAC (added to `auth/types.py`)

- **`worklog.write`** — project-scoped; log work + manage your own worklogs. Added to
  the builtin **member** role (members log their own time) and — via `PROJECT_PERMISSIONS`
  — the admin role. `test_authz.py`'s pinned member set was updated to match.
- **`timesheet.view`** — workspace-scoped; see *other people's* timesheets. Held by
  workspace/instance admins (like `cycle.manage`). Without it, `/timesheet` scopes to the
  caller's own worklogs regardless of the `user_id`/`team_id` filters — you can always
  see your own time.

The migration (`b154d8429f77`) backfills `worklog.write` into existing builtin
admin/member role rows and seeds the default categories for existing workspaces
(new workspaces get categories from a `workspace.created` in-txn hook, like role seeding).

### Timesheet aggregation (`timesheet.py`)

Returns **flat entries** (not pre-pivoted cells) so one query serves every view the UI
needs — the frontend pivots into day/week/month grids and drills down by day, employee,
or issue. Recomputed per request (no materialization), like the reporting module. Joins
`work_items`/`projects` read-only to filter by workspace/project and build issue keys — a
tolerated inward read of dependency tables, mirroring reporting's direct read of `events`.
Team filter expands via `teams.service.list_team_members`; a caller without `timesheet.view`
is forced to `user_ids = {self}`.

## Frontend

- **Issue page** (`components/items/TimeTrackingPanel.tsx`, wired into `ItemDetailBody`):
  shown only when `GET /projects/{id}/timelogging` reports enabled. Estimate/logged/
  remaining bar, inline estimate editor (`item.update`), a compact log-work form
  (duration/date/category/note, `worklog.write`), and the worklog list with edit/delete
  for own entries (or any as a `project.manage` manager).
- **Timesheet route** `/timesheet` (`routes/timesheet.tsx`): period toggle (Day/Week/
  Month) + prev/today/next nav, filters (project always; team + person only with
  `timesheet.view`, else "Your timesheet"), group-by Issue/Person, and a grid (day
  columns × rows, per-day + row + column totals) whose rows expand to the underlying
  entries — the drill-down. Pure pivot/date helpers in `lib/timesheet.ts`; client-side
  duration formatting in `lib/duration.ts`.
- **Settings** `/settings/timelogging`: per-project enable toggles (`project.manage`) +
  work-category management — add/rename/archive (`workspace.manage`).

## Known simplifications

- **`timesheet.view` is workspace-admin-only** (workspace-scoped, like `cycle.manage`);
  custom roles can't currently be granted workspace-scoped permissions, so "roles that
  grant it" is satisfied by the admin role. Everyone can always see their own timesheet.
- Timesheet is **unpaginated and recomputed per request** (fine at prototype scale). It
  includes worklogs from projects later disabled (data isn't deleted). The frontend
  person filter is single-select (backend accepts multiple `user_id`).
- Estimate is a single **original estimate**; remaining is `estimate − logged` (no
  separately-adjustable remaining). `worked_on` is a plain Date (no time-of-day).
- Work categories have no hard DELETE (archive instead); `worklog.category_id` is
  `ON DELETE SET NULL` as a safety net.
- Editing/deleting a worklog does **not** require the project still be enabled (cleanup
  stays possible after disabling); only creating worklogs/estimates does.
