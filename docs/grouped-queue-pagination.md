# Grouped views and service queues — RADD-1201

Grouped boards and grouped lists now use `GET /items/grouped`. The server applies
query/project scope and row visibility, then ranks issues within each column/lane
combination before paging. Each response includes up to 20 populated combinations,
25 issues per combination, and complete column/lane counts. More rows append within
the current group set; a separate group-set navigator handles large numbers of
combinations. Empty configured groups remain available as drop targets. Explicit
SLQ order is respected within groups, otherwise manual rank applies. Hidden columns
and the visible noncompleted cycle set constrain retrieval. Broad select-all is
not offered for this partitioned surface; loaded-row selection remains available.

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
