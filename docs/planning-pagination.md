# Planning pagination — RADD-1197

The old route fetched a global issue page before grouping it into visible cycles.
Completed-cycle issues and closed backlog issues were then removed by grouping.
With a large Jira import, this could leave every group empty while the header
still advertised thousands of matching issues.

Planning now retrieves the issues in visible, noncompleted cycles independently
of the open, unscheduled backlog. Only that backlog uses the page picker. Project
scope, query filters, cycle visibility and saved ordering remain effective.
Without explicit ordering, requests sort by workflow category, priority descending,
updated time descending and issue number. An explicit rank order restores manual
reordering. Broad select-all is disabled here; loaded-row selection remains available.

Sprint retrieval automatically loads ten 200-item pages, then offers Load more.
The header reports loaded/total sprint items separately from the backlog count.
Sprint group totals describe loaded rows until retrieval completes. Backlog page
changes neither remove sprint rows nor restart their fetch.

Verification: `web/scripts/planning-pagination-proof.mjs` exercises the built SPA
with 201 sprint issues across two API pages, 401 backlog issues, and a historical
14,704-item global result. It verifies that no global issue page is requested and
that all sprint rows survive moving to backlog page two. `test_slq.py` checks the
backlog partition and default sort compile against the actual SLQ implementation.
These are synthetic proofs, not a replay of the Emden production dataset.

Follow-up RADD-1201 covers ordering and pagination in other grouped boards and
service queues; this change is scoped to Planning.
