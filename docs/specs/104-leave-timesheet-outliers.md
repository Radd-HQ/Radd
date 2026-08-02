# Spec 104 — Leave, team holidays & timesheet outlier flags

User ask: (1) workdays + daily work hours config (already existed — see below);
(2) the timesheet's By-person view flags days logged under/over configurable
bounds so coordinators spot them; (3) "Leave": users record absence periods that
show on the timesheet AND dim the person with an away marker everywhere their
name/avatar appears; admins define per-team public HOLIDAYS (regional teams
differ — that's the point).

Decisions (user-confirmed): explicit min/max settings (not derived from
hours-per-day); self + team-steward + admin authz, NO approval flow; indicator
reaches everywhere via the shared Avatar/PersonName primitives.

## Config

- `WORK_WEEK_DAYS` (instance + project) and `TIMELOG_HOURS_PER_DAY` (instance)
  pre-existed (specs 35/67) — reused, not duplicated.
- NEW settings-cascade keys (instance scope, Settings → General):
  `TIMESHEET_DAY_MIN_HOURS` (default 6) / `TIMESHEET_DAY_MAX_HOURS` (default 10)
  — env fallbacks `timesheet_day_min_hours`/`_max_hours` in `config.py`.

## `leave` module (optional bootstrap plugin)

- `leave_periods`: ONE subject per row — `user_id` XOR `team_id`
  (check-constrained), `kind` leave|holiday (team target ⇒ holiday, enforced),
  `label`, inclusive `start_date`/`end_date`, `created_by`. FKs CASCADE.
  Holidays expand to the team's CURRENT members at READ time, never
  materialized, so membership changes are always honored.
- Authz: own leave = anyone; another user's = a steward of any shared team
  (`teams.is_team_steward`) or instance admin; holidays = admin only.
- API: `POST/DELETE /leave`, `/leave/mine`, `/leave/holidays` (org-visible),
  `/leave/users/{id}` (self/steward/admin), **`GET /leave/current`** (who is
  away TODAY, longest end date per user — the ONE cached query the app-wide
  indicator renders from), **`GET /leave/calendar?start&end`** (spans
  pre-expanded per member — the timesheet joins these onto its day grid).
- Events `leave.created`/`leave.deleted` ("People" trigger group; trigger
  snapshot now 67).
- Merge/delete semantics: a user MERGE repoints leave (one person keeps their
  absence); hard DELETE destroys it first like worklogs — a successor must not
  show as on vacation they never took (`_MERGE_REPOINT` + `delete_user`).
- Tests: `tests/test_leave.py` (authz, holiday expansion, current-view,
  subject validation).

## Timesheet

- `Timesheet` payload carries resolved `day_min_hours`/`day_max_hours`/
  `work_days` so grid and settings can never disagree.
- By-person view ONLY (a row is one human): completed days (`day < today`)
  tint amber when under min (workdays only; zero-hour workdays included) and
  red when over max, with explanatory tooltips. Leave/holiday days are exempt
  and render the away chip + logged hours if any. Person rows gained avatars.

## The everywhere-indicator

- `components/PersonName.tsx`: `useOnLeave`/`useOnLeaveIds` over
  `currentLeaveQuery` (5-min stale+poll) + `PersonName` (name + amber `away`
  CHIP + "until" tooltip) + `AwayChip`.
- `Avatar` renders a presence-style amber STATUS DOT (ring, per-size) + dim +
  tooltip — anchored INSIDE the circle element (a wrapper span stretched under
  flex parents and slid the badge away; found in the comment thread).
  Iconography note: the first cut used a TreePalm glyph — it smears below
  12px; dot + word replaced it on user feedback.
- Swept sites: issue rail assignee/reporter, new-item modal, bulk bar, cycle
  page + timesheet person filters, form defaults, transition approvers, view
  sharing transfer, delete-user successor, comment author lines; string-label
  chip pickers (team managers, role holders, form sharing) suffix `(away)`;
  the participants REMOTE fetches `/leave/current` itself (federated bundle,
  rebuilt). Exception: automations set-assignee stores EMAILS (no user id) —
  plain text, no indicator.
- SPA: `Settings → Leave` (CalendarOff icon, always visible): my-leave CRUD
  for everyone; holidays list org-visible, CRUD admin-only.
