# Planning workflow — RADD-1197 / RADD-1202

Planning is a scheduling screen with independently fetched sections. It no longer
paginates a global issue result and then discards historical/completed rows.

## Sections and controls

1. Active sprints first, ordered by date; dated upcoming sprints follow, then
   undated drafts. Empty scheduled sprints remain available as drop targets.
2. **Needs rescheduling** contains open issues whose current sprint is completed,
   whether explicitly closed or past its end date. Each row names its source
   sprint. Users can move work into a live sprint or the backlog; this section
   is not itself a writable sprint and nothing is moved automatically.
3. **Backlog** contains only open, unscheduled issues. Search by title, Priority,
   Recently updated and Manual ordering apply only here. Only its own result
   controls the backlog pager. Priority is the initial ordering.
4. **Completed sprint history** is explicitly opened and selects one historical
   sprint at a time. Finished/canceled work appears here; unfinished historical
   work stays in Needs rescheduling. History rows are not drag sources/targets.

Sprint issues always retain manual rank order. Completed/canceled issues in
active sprints are shown by default, with a personal **Show completed issues in
active sprints** toggle. Upcoming/draft sprints show open work.

Collapse state, the completed-work toggle and backlog ordering are personal to
an account/view. Search and history selection are session state. Hiding a sprint
is a shared view setting, restricted to view editors; **Restore N hidden sprints**
makes hidden scope explicit. Planning fixes the section order rather than applying
an old arbitrary column order. Backlog and rescheduling cannot be hidden.

Saved and temporary query conditions, project constraints and cycle-name filters
remain effective. A visible note explains that these may exclude completed work
even when the display toggle is enabled. Planning's order controls replace the
query's ORDER BY for their respective sections. Basic Planning needs no query.

## Queries, counts and bounded loading

`planning-query.ts` builds the partitions before fetching. `cycle.status` is a
queryable derived lifecycle (active/upcoming/draft/completed), using the same SQL
status expression as the cycle directory. It permits equality and membership,
respects restricted cycle fields, and runs inside the normal authorized issue
query. No migration or automatic repair of existing issues is required.

Counts describe matching open sprint issues, open backlog and issues needing
rescheduling. The backlog count follows its search. Individual section counts
show loaded/matching totals where available; sprint progress describes loaded
rows until sprint loading finishes. Empty states distinguish unscheduled work,
no matching search/filters, historical work and incomplete loading. Count failures
are surfaced rather than silently reported as zero.

Sprint retrieval automatically loads at most ten 200-item pages before offering
Load more. Rescheduling and history load one 200-item page initially, with explicit
Load more. Backlog page/search/order changes do not restart the sprint stream.
Selection and bulk actions operate on loaded rows; manual reordering is disabled
in automatically sorted backlog and rescheduling sections.

## Verification

`web/scripts/planning-pagination-proof.mjs` drives the built SPA against a local
fixture API. It checks more than 200 sprint rows, 401 independently paginated
backlog rows, active/upcoming/draft ordering, unfinished historical work, completed
work visibility, lazy history, search/empty states, backlog sorting, personal
collapse, shared hide/restore, rescheduling drops, reopening and read-only controls.
Its screenshot is `/tmp/radd-planning-workflow-proof.png`.

`server/tests/test_slq.py` checks the lifecycle partitions against real database
rows, including date-expired and explicitly closed sprints, null cycles, paging,
invalid lifecycle values and read restrictions. The full backend suite passed
2,719 tests with 4 skipped during this change.

These implementation checks use local fixtures/databases. No company deployment,
saved view or issue is changed by the tests.
