# Large views: performance and navigation review

RADD-1203 · 17 September 2026. Investigation and proposed design; the loading
redesign below is not implemented. Follow-ups: RADD-1204, RADD-1205, RADD-1206.

## Immediate local repair

The frontend generated `cycle.status` queries, while localhost:8000's backend
process had started on September 14 without reload. Source contained the new
field, but that process did not. Its database was at `d1175boardcols`.

Applied the two pending migrations (nullable imported comment authors and
storage email-image opt-in), reaching `d988emailimages`, then gracefully
restarted the API from the same server directory and inherited environment.
The new process serves `/health` successfully; HTTP SLQ validation accepts
`cycle.status = active`, and active/completed-cycle item reads return 200.
No issue content or company deployment was changed. The temporary local
read-only profiling token was revoked after use.

Development updates must keep code, schema, backend process and built frontend
together. `sh scripts/dev.sh` already migrates, rebuilds and replaces the server;
rebuilding only the SPA does not reload Python. `/health` reports `dev`, which
alone does not establish which checkout revision a running process loaded.

## Evidence and limits

Read-only localhost HTTP samples, three sequential requests each, no network or
CPU throttling, using an administrator's temporary token restricted to
`item.read` and `cycle.read`. Dataset: 501,297 visible items. This is a broad
local dataset, not a Cinesite deployment benchmark or a before/after regression
comparison. Other local activity and cache warming were not controlled.

| Request | Rows | Times (ms) | Response bytes |
| --- | ---: | --- | ---: |
| First list slice, limit 25 | 25 | 301, 219, 516 | 28,656 |
| First list slice, limit 200 | 200 | 387, 295, 277 | 376,036 |
| List slice, offset 10,000, limit 200 | 200 | 1,060, 1,055, 616 | 440,841 |
| Open-item count | — | 653, 793, 709 | 15 |
| Cycle directory | 91 | 43, 34, 17 | 25,846 |
| Needs rescheduling | 14 | 367, 179, 179 | 33,610 |
| Grouped by state category, 25 per cell | 150 | 7,019, 7,420, 6,573 | 281,919 |

Direct service instrumentation with the same token scope reproduced the global
grouped request at 6,633ms: 210 SQL executions, 5,962ms in SQL. The ranked row
selection took 4,741ms and grouped counting took 1,000ms. A project-scoped DEV
service call returned 100 rows in 196ms with 34 SQL executions. These are single
profile runs, not HTTP latency percentiles. An unrestricted administrator profile
was materially faster (1,800ms globally), so role/scoped-token performance must
be measured separately; do not optimize by bypassing permission checks.

Built-SPA browser traces used synthetic fixture data with 200 backlog rows and
one recovery row, a 1600×1000 viewport, and immediate local fixture responses:

| Expanded sprint rows | DOM elements | Long tasks | Largest task | Item / count requests |
| ---: | ---: | ---: | ---: | --- |
| 201 | 10,232 | 7 | 138ms | 4 / 4 |
| 2,000 | 53,411 | 31 | 514ms | 12 / 4 |

Each is one trace, including initial application loading; not a controlled
render-only comparison. Total long-task duration was 656ms versus 4,842ms.
Collapsing the large sprint reduced DOM elements to 5,410. No browser console
errors occurred. This establishes rendering growth, not its precise impact on
every user's machine.

## What the current implementation does

- Plain lists and queues replace one numbered page. Desktop defaults to 200
  rows, phone to 50, with 25/50/100/200 choices. Queues order before paging.
- Grouped boards/lists fetch 25 rows per cell across up to 20 cells. The shared
  Load more advances all those cells together; another pager selects cell sets.
  Grouping before paging fixes empty columns, but does not make SQL work cheap.
- Planning separates sprint work, backlog, recovery and history correctly.
  Sprint work still auto-loads ten 200-row pages across all visible sprints.
  A large early sprint can consume that budget before later sprint rows arrive.
  Collapsing a sprint removes rendered rows but does not stop its fetches.
- Planning waits for the initial backlog, sprint and recovery reads together;
  a slow section delays healthy sections. It also makes separate counts.
- Lists and boards render all loaded rows. Appending more remains expensive
  even if each individual HTTP response is bounded.
- Item mutations invalidate item-tagged active queries. Accumulated infinite
  pages can therefore refetch; Planning counts use broad entity tags.
- Item list reads include descriptions and hydrated relations. A page limit
  bounds row count, not response bytes or permission/hydration work.
- Normal list paging uses offsets. Ordering ends with created_at without a
  universally unique tie-breaker; concurrent changes can shift page boundaries.
- Reordering normally writes one rank. Global rebalance is a fallback when
  the floating-point gap collapses, not something every drag performs.

## Recommended experience

Keep Show more as the normal browsing interaction. Use independent sections,
bounded rendering and preserved position underneath it; unlimited automatic
scrolling is not necessary. Numbered pages remain useful for audit/report tasks
and as an explicit alternative for people who want page navigation.

Planning should open with a compact jump navigator and active/upcoming/draft
headers, including counts and progress. Initial values below are proposed and
must be tuned through measurement:

```text
Jump to: Current sprint · Next sprint · Needs rescheduling · Backlog

Current sprint       42 open · 8 completed       [Collapse]
  All 50 issues

Next sprint          137 open                    [Collapse]
  First 50 issues
  Showing 50 of 137                  [Show 50 more]

Needs rescheduling   48                          [Collapse]
  Open work with its original sprint

Backlog              8,412 open
  [Search backlog]   [Priority ▾]
  First 100 issues
  Showing 100 of 8,412              [Show 100 more]
```

Each section loads independently. A collapsed section keeps its count and drop
target but stops loading bodies. A large sprint cannot starve another sprint.
Counts can arrive after rows with an honest loading indicator. A failure offers
Retry in that section while the rest stays usable. Completed history stays
explicit and lazy. Small sprints need no Show more button.

### Group statistics are independent of loaded rows

The user's follow-up identified an existing correctness gap: cycle headers fetch
estimate/logged/remaining from the server through `CycleHeaderStats`, but
`groupItemsForView` derives `cycleMeta.done`, `cycleMeta.total` and the progress
bar from the loaded bucket. Those values can change simply because another
page arrives or completed rows are hidden. Independent loading must not retain
that behavior.

Use permission-filtered server aggregates for the whole sprint within the
current project scope, including completed work even when its rows are hidden.
Label these as sprint totals. Separately show full matching count for current
filters, then the loaded count (for example: "137 sprint issues · 62 match
filters · 50 shown"). General group totals follow the view's filters; all totals
must exclude inaccessible issues. Time stats and issue progress must clearly
identify their scope. Aggregate reads should be batched across visible headers,
and must not require fetching all item bodies or an expensive count per row.

Correct progress/total semantics are a prerequisite for progressive loading.
Tests must establish unchanged aggregates across Show more, collapse, row
virtualization and completed-row visibility; issue mutations still update them.

Use one main scroll container and a compact sticky navigator rather than
multiple nested scrollers. Render rows near the viewport with overscan; preserve
expanded details, keyboard navigation, focus and drag/drop targets when a row
leaves the rendered window. Boards need equivalent per-column loading and
care around variable card heights. Start virtualization with the simpler list.

Opening an issue and returning should restore the same issue and pixel offset,
loaded range, search and sort. Show more keeps existing rows and focus stable.
Selection must distinguish selected loaded rows from all matching issues.
Background changes should update known rows without unexpectedly reshuffling
the list under the pointer; offer an updates indicator and anchored refresh
when membership/order changes. Access revocation cannot wait for that refresh.

For deep browsing, use continuation cursors with an explicit unique tie-breaker
for supported sorts. Deduplicate IDs and define refresh semantics when ranks or
sort fields change; a cursor alone does not guarantee a stable snapshot of a
live dataset. Preserve offset paging where random page access is intentional.

## Implementation order and acceptance

1. **RADD-1204 — query cost.** Separate cheap authorized group aggregates from
   selected-cell row retrieval; profile ranked scans and permission/hydration
   work. Preserve user-configured group order and all visibility restrictions.
   Record EXPLAIN plans and SQL/request counts before choosing indexes. Proposed
   warm-local first-slice target: under one second on the broad fixture, measured
   across roles and scopes, with slow cases reported explicitly.
2. **RADD-1205 — independent progressive loading.** Per-section Show more,
   independent errors, collapsed-section laziness, jump navigation and return
   position. Cover uneven groups, more than 2,000 rows, keyboard/mobile use and
   drag/drop with unloaded destinations. Keep existing semantic partitions.
3. **RADD-1206 — render and refresh budget.** Virtualize loaded list rows, measure
   card rendering separately, narrow response shapes according to configured
   columns, and reduce unnecessary invalidation/refetches. Do not create a second
   permission model or silently omit display fields. Test two users editing,
   slow responses, revoked access, filter changes and prolonged browsing.

RADD-1115 remains the broader performance ledger. This investigation does not
establish concurrent worker throughput, an historical regression, or internal
company readiness. Re-run representative staff journeys after these changes;
the immediate backend mismatch is repaired, the performance redesign is queued.
