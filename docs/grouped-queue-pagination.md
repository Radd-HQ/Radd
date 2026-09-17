# Grouped views and service queues — RADD-1201

Grouped boards and grouped lists use `GET /items/grouped` with a complete
summary and separate cursor windows for individual columns/cells. Counts and
point totals cover the complete authorized result, independently of loaded rows.
Boards load visible cells; grouped lists load visible expanded sections and
continue automatically when scrolling within each section. A searchable group
picker replaces group-set paging. Group bodies have a bounded height so large
groups do not push all later headers thousands of rows away. Small screens use
a shorter scrolling area. Collapse, selection, ordering and drop targets remain
available; empty configured groups remain drop targets. Hidden columns and the
visible cycle set constrain retrieval. Lists ignore a saved board swimlane axis.
Broad select-all is not offered for this partitioned surface; selection refers
to loaded rows. The legacy shared Load more/group pager hook has been removed
(RADD-1217).

The item service exposes its authorized ID query and accepts a selected-ID subset
for final hydration; the subset still passes ordinary visibility/capability rules.
No new dependency from items to slas is introduced.

Queues use `GET /sla-queue-items`, owned by slas. Without explicit SLQ ordering it
sorts open breaches first, earliest open deadline next, then oldest creation and
ID, before selecting the requested page. Settled timers do not drive ordering.
It evaluates live timers in batches of 200 matching IDs, avoiding stale breach
bookkeeping and full issue/timeline hydration for the entire queue. The complete
set of lightweight sort keys must still be evaluated per request: broad queues
with many SLA-bearing issues cost more than an ordinary indexed list. Narrow queue
filters remain useful; no Emden production latency claim has been made. Explicit
saved ordering uses the ordinary database list sort.

Verification includes real database regressions with over 200 issues, the same
six-actor visibility matrix as normal issue lists/counts, and built-SPA HTTP proofs
for grouped loading and queue paging. Browser proofs use fixtures; they do not
change a deployed instance.
