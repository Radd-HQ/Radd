# Spec 59 — Itemless (general) worklogs + categories as first-class timesheet citizens

**Status: built.**

## Problem

Every worklog required an issue (`worklogs.item_id` non-nullable, only
`POST /items/{id}/worklogs`). Meetings/admin/general time had nowhere honest to
go — the workaround is a perpetual catch-all issue polluting boards. And
categories were passive metadata: nothing surfaced "X hours went into Meetings".

## Shape

- **Nullable scope** (migration `43a780816f08`): `worklogs.item_id` nullable; new
  nullable `project_id` + `workspace_id` anchors (FK CASCADE). DB CHECK
  `ck_worklogs_scope`: item-bound rows as before, itemless rows must carry
  `workspace_id` AND `category_id` — **category is an itemless entry's identity
  and is enforced** (schema-required on create; clearing it on update 409s;
  swapping is fine). Item-bound worklogs keep category optional (the 11k-row
  imported corpus stays valid).
- **`POST /worklogs`** (general log): `{project_id | workspace_id, category_id,
  time_spent, worked_on?, note?}`. Project-anchored → `worklog.write` on that
  project + the project's timelogging enablement; workspace-anchored → holds
  `worklog.write` on ≥1 project (the any-project gate — the pinned
  workspace-scope member floor stays untouched). Edit/delete authorization is
  scope-aware (`service.worklog_scope`): project rows as before; workspace rows
  = author (with the general gate) or workspace-scope holders of the atom.
- **Timesheet**: outer-joins items; itemless rows filter by their own
  workspace/project anchor. A project filter keeps only that project's itemless
  rows (workspace-general time belongs to no project). `TimesheetEntry.item` is
  nullable + new top-level `project_key`; worklog events now carry
  `project_id`/`category_id` and a null-safe `item_id`.
- **UI** (categories first-class):
  - **Category strip** under the filters: per-category totals for the filtered
    window ("Meeting 2h 45m · Development 12h · Uncategorized 2h 30m"),
    whatever the grouping. Item logs without category bucket as Uncategorized.
  - **Group by: Category** joins issue/person — rows are amber category tags,
    drill-down shows `person · issue-key-or-"no issue"` per entry.
  - In issue grouping, itemless entries bucket under their **category as a
    first-class row** beside the issue keys (never a blank/missing key); in
    person grouping the drill-down labels them `TD · no issue` / `no issue`.
  - **"Log time" button** on the timesheet header → modal (category REQUIRED,
    optional project anchor, duration/date/note). Item-bound logging stays on
    the issue page's time panel.
- Cycle stats (`cycle_time_totals`) are untouched — they sum item-joined rows
  only, so general time never pollutes cycle estimate/logged/remaining.

## Verified

`tests/test_general_worklogs.py` (anchor + category validation, workspace and
project scoping, timesheet inclusion + project-filter semantics, category-clear
409) + full suite 646 green; live E2E over HTTP (create both anchors, 422 on
missing category, timesheet rows) + screenshots of the category grouping,
strip, drill-down, and modal. Downgrade path deletes itemless rows (documented
in the migration).
