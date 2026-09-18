# Scale audit: 500,000 issues and 100 active users

Date: 2026-09-18. Source checkout: `1ce62ae`.
Target workload confirmed by the user: mixed browsing, search, and editing.
Deployment hardware and replica counts are undecided.

Implementation follow-up: [changes, validation, and remaining scale work](IMPLEMENTATION.md).
This report and its original measurements describe the pre-change audit.

## Assessment

There are confirmed scale defects and substantial concurrency amplification.
Do not treat current performance as established for 100 active users. The
highest priorities are the permission SQL/JIT interaction, read amplification
after edits, search cost, and unbounded worker/report batches. These are
targeted changes to existing components; the evidence does not call for a
complete application rewrite or an immediate database replacement.

This is a broad source audit plus bounded local read profiling. It cannot
prove that every bottleneck has been found. A sustained, authenticated,
100-person workload including committed writes and live workers remains a
separate acceptance test. No production capacity guarantee is made.

No application code, data, indexes, server settings, grants, or worker state
were changed. Test transactions used READ ONLY and rolled back. The JIT
comparison used SET LOCAL inside those transactions. No workers or application
lifespan hooks were started by the probes.

## Environment and limitations

Recorded inventory: [inventory.json](inventory.json).

- Local PostgreSQL dataset: **501,298 issues**, **1,791,684 comments**, 501,298
  search rows, 106 projects, 1,114 accounts, 2,299 teams, 319 field definitions.
- Largest project: **100,864 issues**. Database total size approximately 10 GB,
  including unrelated fixture/import/history storage.
- Only **21,271 live events** at inventory time. History density is not
  representative of a mature half-million-issue installation. No enabled SLA
  policies were present; worker findings are source-verified, not measured
  production worker throughput.
- Local machine: Ryzen 5 5600X, 12 logical CPUs, approximately 31 GiB RAM.
  Shared development machine, not reserved benchmark hardware.
- Application pool defaults used by the probes: 5 retained + 10 overflow
  connections. PostgreSQL reports max_connections=100, shared_buffers=128 MiB,
  work_mem=4 MiB, up to two parallel workers per gather, JIT enabled.
- Direct service profiles exclude HTTP routing, login/session resolution,
  response serialization, network latency, browser rendering, and realtime
  fan-out. The load generator is a separate Python process with its own pool;
  it is not traffic through the running web server.
- Admin and restricted-member paths were both exercised. The sampled member
  could see 2,859 issues across the instance. Different grants/team structures
  will produce different plans and costs.
- Read transactions imposed a 15-second statement timeout. Burst operations
  had a 45-second timeout. These are probe guardrails, not claims about the
  deployed timeout configuration. The inspected database's default statement
  timeout was **0 (disabled)**. Thus the failed stress queries demonstrate
  exceeding a test budget, not that production would return that same error
  after 15 seconds; production may retain them and their connections longer.
- Timings are diagnostic observations, not statistically stable SLAs. Cache
  warmth, query compilation, and concurrent work affect them.

## Measurements

Source: [validated service profiles](read-profile-validated.json). The initial
[exploratory run](read-profile.json) includes an incorrectly specified board
lane and an unreadable member issue; those failed cases were corrected in the
validated run and must not be used as successful performance measurements.

| Operation | Admin | Restricted member | SQL statements, admin / member |
| --- | ---: | ---: | ---: |
| One issue detail | 241 ms | 243 ms | 29 / 38 |
| Project list, 25 items | 37 ms | 180 ms | 30 / 37 |
| Cross-project list, 25 items | 97 ms | 275 ms | 115 / 66 |
| Project state summary | 229 ms | 204 ms | 5 / 16 |
| All-project state summary | 493 ms | **8,390 ms** | 4 / 14 |
| All-project assignee summary | 351 ms | **7,959 ms** | 5 / 15 |
| Project board cell, 25-item limit | 64 ms | **1,946 ms** | 32 / 49 |
| All-visible count | 106 ms | **1,143 ms** | 4 / 8 |
| Exact-looking key through search | 211 ms | 883 ms | 6 / 19 |
| Common-word search, `render` | **1,218 ms** | **2,505 ms** | 6 / 19 |
| Report's initial visible-ID universe | **1,539 ms / 501,298 IDs** | 1,311 ms / 2,859 IDs | 4 / 8 |

The earlier independent run reproduced member all-project summaries at
8,218 / 8,021 ms. Admin search varied from 1.2 to 2.3 seconds, illustrating why
two local runs are not sufficient for a latency percentile claim.

### Permission SQL diagnosis

[Read-only diagnostic](scale-diagnostics.json): identical summary output hashes
with transaction-local JIT off and on.

| Configuration | Service time | EXPLAIN ANALYZE execution |
| --- | ---: | ---: |
| JIT off | **648 ms** | **339 ms** |
| JIT on | **7,924 ms** | **7,880 ms** |

The JIT-on plan compiled 7,536 functions. Its aggregate JIT time across parallel
participants was 22.6 seconds; this is accumulated worker time, not wall time.
The authorized query had approximately 1,482 bind parameters. Large repeated
per-project permission expressions are a major contributor. This identifies
a promising local mitigation, not permission removal or a blanket rule to
disable JIT for every analytical workload.

### Concurrency diagnostic

One synchronized burst, one representative member, fresh transaction per
operation. Mix: 50% issue detail, 30% project lists, 10% common-word search,
10% all-project state summaries. This is **100 simultaneous service reads**,
not 100 distinct people or a sustained mixed read/write session test.

| Burst | Success | Median completion | p95 completion | p95 connection acquisition | Wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10, default JIT | 10/10 | 1.75 s | 9.25 s | 0.029 s | 9.26 s |
| 100, default JIT | 94/100 | **16.02 s** | **33.68 s** | **27.11 s** | 41.04 s |
| 100, transaction-local JIT off | 100/100 | **9.45 s** | **17.34 s** | **14.78 s** | 18.22 s |
| 100, JIT on again | 95/100 | **15.75 s** | **34.69 s** | **26.56 s** | 41.28 s |

Sources: [10-read burst](read-burst-10.json), [100-read burst](read-burst-100.json),
[100 reads with JIT off](read-burst-100-jit-off.json), and
[JIT-on repeat](read-burst-100-jit-on.json). The six first-burst failures
were database OperationalErrors; that first version of the recorder retained
the exception class, not its message. They must not be relabeled as a specific
database error without additional evidence.
The repeated JIT-on run recorded five explicit statement-timeout failures.
Its similar slowdown after the JIT-off run reduces the likelihood that cache
warmth alone explains the comparison. These remain single bursts per variant,
not a randomized multi-run capacity benchmark.

Connection acquisition includes connection creation/checkout and time spent
waiting for the pool/event loop, not purely PostgreSQL execution. Loop stalls
reached 1.39 seconds in the default 100-read run. With JIT off the maximum was
624 ms and p95 371 ms. Eliminating SQL compilation overhead does not eliminate
Python work, query volume, or pool waiting. Completion percentiles include
queueing from the instant the burst was submitted.

## Findings and remedies

### S01 — Permission SQL becomes very expensive with ordinary member scopes

**Priority: P0. Measured.** Admin-only benchmarks miss this.
[relation_read_clause](../../server/src/radd/modules/items/service/visibility.py)
builds a separate OR branch for each project, including repeated row guards
and participant subqueries. [Grouped reads](../../server/src/radd/modules/items/grouped.py)
wrap the authorized ID selection in another work-item query. The resulting
query triggers expensive JIT compilation in the measured environment.

Group projects with identical effective predicates, reuse common permission
subexpressions, and inspect plans for the grouped/count/list/search variants.
Evaluate transaction-local JIT policy for latency-sensitive reads first.
Require authorization parity for public/restricted/own/team/participant and
cross-project references. Never replace the actor predicate with an admin path.

### S02 — An edit can make unrelated clients repeat expensive reads

**Priority: P0/P1. Source-verified amplification.**
[Realtime query matching](../../server/src/radd/modules/realtime/hub.py) matches
entity type and optional project, not item identity.
[Issue-by-key queries](../../web/src/lib/queries/items.ts) and allowed-transition
queries carry entity tags without project/item scope. Thus an item update in
another project can target those active queries. Mutations also immediately
[invalidate all local item caches](../../web/src/lib/item-mutations.ts), after
seeding the updated item, then receive the websocket event.

Project-scoped subscriptions and 200 ms coalescing already help, but unscoped
details/counts remain broad. With 100 open detail views, a single edit can
trigger at least 100 detail refetches if each has that active subscription,
plus related transition/count/list requests. That is a code-derived example,
not an observed 100-browser traffic measurement.

Add server-validated item scope to exact-record subscriptions, distinguish
record refresh from collection membership/order changes, and avoid redundant
self-refresh when the mutation response already supplies the authoritative
record. Keep conservative invalidation for arbitrary SLQ until dependency
tracking is proven correct. Test with edits in unrelated and related projects.

### S03 — Whole-project batches can fail outright above 65,535 parameters

**Priority: P0 for affected paths. Reproduced.**
[items_by_ids](../../server/src/radd/modules/items/service/queries.py) expands
every ID into a bind. Passing the largest local project's 100,864 active IDs
raised `OperationalError: number of parameters must be between 0 and 65535`.
[SLA](../../server/src/radd/modules/slas/engine.py) supplies just such a full
project batch. Report timeline and large descendant helpers use similar
unbounded IN lists; their end-to-end failures were not separately measured.

Use authorized database subqueries/joins or bounded chunks. Arrays can avoid
the parameter-count ceiling, but still loading all rows into Python would
retain the memory/CPU problem. Verify correct complete results across chunks.

### S04 — SLA worker performs work proportional to whole project size

**Priority: P0 when SLA is enabled. Source-verified.**
Every 60 seconds by default, [the engine](../../server/src/radd/modules/slas/engine.py)
loads all non-archived IDs, all corresponding full items, and executes one
joined `item_ref` lookup per item. Terminal items are removed only afterwards.
The timer evaluator reconstructs event histories and can walk calendar days
for old issues. One transaction covers the sweep.

Filter eligible/open rows before hydration, process bounded batches, fetch
refs once per batch (or only for emitted events), and persist timer state plus
next evaluation deadlines. Separate the worker process from interactive web
traffic. Existing fixture has zero enabled policies, so it conceals this cost.

### S05 — Reports reconstruct full histories in memory on each request

**Priority: P1; prerequisite for large reporting usage. Source + measured setup.**
[Reporting](../../server/src/radd/modules/reporting/service.py) materializes the
whole authorized ID set before narrowing some cycle reports. That step alone
returned 501,298 UUIDs in 1.54 seconds for the admin. [Timeline reconstruction](../../server/src/radd/modules/reporting/timeline.py)
then loads full event payloads for all relevant history, even for a short
display window. Cumulative flow and burnup repeatedly walk these timelines
for each time bucket. Multiple report widgets repeat the work.

Maintain incremental state-transition/cycle projections, aggregate in SQL,
and use bounded history reads with appropriate starting snapshots. Cache only
with correct scope/permission isolation and invalidation. Local 21k events
are insufficient to measure years of production history. Measure with millions
of history rows before accepting this path.

### S06 — Search is already slow at half a million rows

**Priority: P1. Measured plans.**
[Search](../../server/src/radd/modules/search/service.py) uses `key ILIKE` with
no matching key index in the inspected database. An exact-looking key scanned
the full search table; its plan took about 170 ms before other service work.
The FTS branch runs too. The existing tsv GIN index is useful, but a common
term still requires ranking many matches; `render` matched roughly 223k rows
in the admin plan and took 1.2–2.3 seconds at service level. Member predicates
add cost. The query selects complete index rows including large text/tsv.

Provide an indexed exact-key/alias path and an appropriate prefix index for
key completion, preserve authorization, narrow selected columns, and profile
common-term ranking and snippet generation independently. Evaluate semantic
search separately: when enabled it can additionally wait up to the configured
two-second hybrid budget while the request transaction holds a connection.

### S07 — Pool occupancy and synchronous Python work limit concurrent reads

**Priority: P1. Measured burst + configuration.**
[Pool](../../server/src/radd/db.py) defaults allow 15 connections per process.
[Production container command](../../Containerfile) starts one web process;
background loops run in that process by default. Requests retain their DB
transaction through service execution/response construction. Heavy reads and
workers therefore compete for CPU, connections, memory, and disk bandwidth.
The burst showed p95 acquisition time of 27.1 seconds (14.8 with JIT off).

Reduce work per action first, then benchmark web replicas and pool sizes with
an explicit total PostgreSQL connection budget. Keep one worker owner per the
documented consumer model. More replicas multiply both connections and some
realtime polling; they are not a substitute for fixing unbounded algorithms.
Add checkout-wait, SQL duration, request queue, event-loop lag, and worker-lag
metrics. Neither tuning nor hardware sizing was applied by this audit.

### S08 — Cross-project hydration repeats work per distinct project

**Priority: P1. Measured query count.**
[list_items](../../server/src/radd/modules/items/service/listing.py) loads
project/field/grant context inside per-project loops, even though project
permissions already have batch APIs. A 25-row cross-project result used 115
SQL statements for the admin, versus 30 for a project list. Thirteen project
and field/grant query shapes repeated in the sample.

Batch project records, field definitions/scopes, and grant data for the page;
reuse actor subjects and pre-resolved permissions. Keep per-project read
filtering semantics. Relation hydration is already batched per relation; the
remaining issue is repeated per-project preparation and many sequential round
trips, not an HTTP permission request for every displayed field.

### S09 — Custom-field and contains filters lack supporting indexes

**Priority: P1 for commonly used filters. Source + index inventory.**
Work-item title contains filters use `%term%`; custom-field predicates use
JSONB containment or extracted/cast values, and custom sorts use expressions.
The inspected work_items indexes include neither a custom_fields GIN index,
typed custom-field expression indexes, nor title trigrams. The field registry's
`indexed` flag is stored metadata; no implementation creates those indexes.
Exact counts/group summaries evaluate all matches regardless of the 25-row
display limit. Deep OFFSET pages also do increasing work.

Select indexes from real high-frequency predicates and EXPLAIN plans; account
for their write/storage cost. Preserve numbered-page behavior where needed,
use existing cursor paths where suitable, and avoid eager exact counts where
the UI can accept deferred or explicitly approximate values.

### S10 — Batched queue badge HTTP calls still run counts sequentially

**Priority: P1 where many queues/widgets are open. Source-verified.**
[view_counts](../../server/src/radd/modules/views/counts.py) awaits a separate
authorized count for each view, plus query/field resolution. The frontend
[polls every minute](../../web/src/lib/queries/views.ts), up to 50 view IDs per
batch, and item events invalidate these counts as well. One HTTP batch does
not make this one database aggregate. Widgets can add their own counts.

Share common authorized scope preparation, consolidate compatible aggregates,
prioritize visible badges, and debounce/coalesce invalidations. Test 10/50
queues with realistic SLQ and 100 clients. Avoid a cache that merges users with
different row permissions.

### S11 — Issue opening creates substantial fan-out and duplicate catalog work

**Priority: P1 for latency/concurrency. Browser trace from this investigation.**
A cold anonymous local issue page made 40 API calls including its shell, 28
after the issue/project lookup. Field writability was one batched request.
Three complete user-directory variants, field catalog, repeated project/space
summaries, and plugin calls are additional work. The field catalog response in
that trace was about 153 KB. Anonymous errors and cold-shell work mean that 40
is not an authenticated warm-open request budget.

Coordinate critical initial data, reuse project metadata, show selected people
from the issue and load bounded choices on interaction, give shared summaries
appropriate freshness, and avoid requests for disabled/unavailable features.
The two project directory variants additionally call an entitlement helper
that expands granted teams one at a time. Test large teams/grant catalogs.

### S12 — Ordinary writes and bulk operations repeat full read pipelines

**Priority: P1 for editing/bulk load. Source-verified; writes not benchmarked.**
[update_item](../../server/src/radd/modules/items/service/core.py) hydrates the
full item before the change and again for its response/event snapshot. This
includes relation/count/permission work. Bulk updates call that whole service
per item (up to 500), with savepoints inside the encompassing transaction.
They emit downstream search/notification/automation events as well.

Retain the audit and authorization contract while batching shared metadata,
avoiding unchanged relation reads where proven safe, and using bounded async
jobs for large bulk actions. Measure transaction/lock time and downstream
event lag, not only PATCH response latency.

### S13 — Issue creation serializes by project; validation can prolong the lock

**Priority: P1 when high write/import/intake concurrency is expected. Source-verified.**
[Number allocation](../../server/src/radd/modules/projects/service.py) updates
the project row. That lock remains through subsequent create work and the
intake hook. The configured validation budget is 25 seconds and can include
AI/external checks. Requests creating in the same project can queue behind a
slow validation. Ordinary edits do not all acquire this number lock.

Run expensive preflight outside the allocation critical section where the
correctness contract permits, or separate number allocation from slow external
validation with a deliberate gap/commit policy. Measure same-project creates
and imports in a disposable environment. No concurrent writes were issued here.

### S14 — Event growth affects history, indexing, and background throughput

**Priority: P1/P2 depending on retained history and edit rate. Source-verified.**
Events retain full issue snapshots. History and report lookups use JSON paths
such as `payload.item.id` and `payload.item.project.id` that lack dedicated
indexes in the inspected database; history's result cap does not avoid the
cost of finding matching related events. Consumers read full event rows in
batches and most handle each event sequentially. Comment indexing re-reads
all public comment bodies for the changed issue. Subject changes/startup can
scan work_items/search_index to repair mirrors. Notification fan-out performs
per-recipient authorization reads.

Use indexed canonical item/project references for event access, consider
partitioning/retention only with audit/report/replay requirements preserved,
coalesce safe repeated search updates, batch recipient context, and monitor
consumer delay under steady edits/imports. A mature-event fixture is essential.

### S15 — Rare global rank rebalance is still an interactive whole-table write

**Priority: P2; rare but potentially disruptive. Source-verified.**
[Rank rebalance](../../server/src/radd/modules/items/service/queries.py) uses
one set-based UPDATE, an improvement over per-row writes, but touches every
issue when floating-point spacing collapses during reorder. At 500k rows it
can create broad locking/WAL/index-maintenance work in an interactive request.

Measure the collapse path in a disposable copy; evaluate wider/local rank
spacing or a controlled rebalance strategy that preserves cross-project order.
Do not invoke this path on the shared dataset merely to time it.

### S16 — Broad roadmaps and deep browsing still accumulate full objects/DOM

**Priority: P2; scope-dependent browser and refresh cost. Source-verified.**
Roadmap match streaming pauses after 15 automatic pages, but
[roadmapMembersQuery](../../web/src/lib/queries/views.ts) separately walks every
membership page sequentially via `allRelationRows`, retaining full Item objects.
Loaded board/list pages also retain DOM; supplementary queries/polls cover
loaded batches. Broad views, long browsing sessions, and invalidations can
therefore grow memory and refetch work despite bounded initial pages.

Use a dedicated bounded/compact membership model without substituting partial
objects into full Item caches. Establish loaded-row/memory budgets. Any
virtualization must preserve selection, keyboard navigation, browser Find,
drag/drop, and roadmap scheduling semantics.

### S17 — Expensive reads have no application-level database execution budget

**Priority: P1 for overload behavior. Configuration + source; cancellation unmeasured.**
The app configures an idle-in-transaction timeout, which does not limit an
actively executing SELECT. The inspected DB default statement_timeout is 0.
There is no per-read SQL timeout in the reviewed item/search/report handlers.
A costly query can therefore retain a pool slot well beyond a useful
interactive latency budget. Existing frontend AbortSignals stop fetches, but
do not establish that server-side SQL has stopped; that must be tested through
the actual HTTP server.

Define execution/admission budgets for expensive reads, separate heavy jobs
from interactive capacity, and test cancellation on rapid search/navigation.
Use explicit overload responses and preserve transaction rollback. Avoid
applying an indiscriminate timeout to legitimate long-lived streams or writes.

## Existing protections worth keeping

- Ordinary item responses have a 200-row API maximum; board cells are bounded.
- Item/project-number, parent, state, assignee, team, cycle, and rank indexes
  exist. Comment feeds have a parent/order index and cursor pagination.
- Project permission resolution, field grants, relation hydration, rollup
  inputs, and SLA chips already have some batching. Field checks are not
  individually sent over HTTP.
- Boards use summary/cell windows, and the browser requests visible sections.
- Realtime coalesces changes, uses project scopes where supplied, skips initial
  reconnect invalidation, and does not hold a DB connection per idle websocket.
- Streaming/file transaction handling and password hashing have existing
  safeguards. The read problem is not that every idle user consumes a DB slot.

## Recommended implementation order

1. Reduce permission-expression duplication and evaluate the measured JIT
   mitigation with permission parity tests; fix unbounded IN batches.
2. Stop unrelated issue refreshes and excessive badge/catalog fetching. Batch
   page hydration metadata; implement indexed key search and profile common FTS.
3. Make SLA evaluation bounded/incremental and replace on-demand full-history
   reporting with projections. Scope operational work to a separate worker.
4. Instrument and run the authenticated mixed-load test below. Then choose
   hardware, replica/pool sizes, and targeted indexes from measured limits.

## Acceptance test for 100 active users

Use an isolated production build and disposable production-shaped database.
Existing perfseed tooling writes extensively and was **not run** in this audit.
Augment the fixture with realistic retained events, watchers, active SLAs,
custom fields, links, attachments metadata, and project-size skew. Include
representative AD/team/nested-group grants, row restrictions, and internal
comments. Use 100 distinct identities, not an admin or a shared actor.

- Workload starting point: 50% issue opens, 25% board/list navigation, 15%
  searches, 10% edits/comments. Validate this distribution with staff usage.
- 100 logged-in sessions with persistent websocket connections, realistic
  5–15 second think times, normal cache reuse, and both related/unrelated
  projects. This represents roughly 6.7–20 user actions/second; HTTP/SQL request
  rate must be observed because actions fan out differently.
- Ramp 1 → 10 → 25 → 50 → 100 users, then hold 100 for at least 30 minutes.
  Separately test synchronized opens and a reconnect burst. Repeat runs with
  stable data/configuration and record warm/cold cases separately.
- Include issue edits, state transitions, comment posting, restricted fields,
  same-project creates, 500-item bulk jobs, and imports as distinct scenarios.
  Route outbound mail/webhooks/AI to test doubles or local sinks; preserve
  authorization, validation, and worker costs. Do not bypass normal permissions
  or silently remove product rate limits from the reported configuration.
- Browser cohort: time click-to-useful-detail, controls-ready, input delay,
  layout movement following clicks, DOM count, memory, and long tasks. Do not
  use network-idle as the sole readiness signal in a polling/realtime app.
- Server/DB: p50/p95/p99 per endpoint and user action, 5xx/timeouts, actual
  request/SQL counts, bytes, checkout wait, event-loop delay, CPU/RSS, IOPS,
  lock waits, active DB connections, temp spills, slow-plan fingerprints,
  and event/search/SLA/notification lag. Separate successful and failed latency.
- Track whether one user's edit refreshes unrelated viewers. Check both live
  correctness and amplification. Confirm no unauthorized data after caching,
  permission changes, account switching, or batching.

Proposed initial acceptance budgets to agree before implementation: warm issue
open p95 < 1.5 s; first useful board p95 < 2 s; common search p95 < 1 s; ordinary
PATCH p95 < 1 s; unexpected failures < 0.1%; no growing pool wait or worker
backlog during the steady phase. These are targets, not current promises.
Search results and notifications should converge within an explicit budget,
and SLA processing must keep up with its evaluation interval. CPU/memory and
connection headroom must remain adequate for the tested bursts.

## Reproduction

From `server/`, using its existing virtualenv and local configuration:

```sh
.venv/bin/python ../research/scale-audit-2026-09-18/profile_reads.py /tmp/read-profile.json
.venv/bin/python ../research/scale-audit-2026-09-18/inventory.py
.venv/bin/python ../research/scale-audit-2026-09-18/diagnose_scale.py
.venv/bin/python ../research/scale-audit-2026-09-18/read_burst.py 10
.venv/bin/python ../research/scale-audit-2026-09-18/read_burst.py 100
.venv/bin/python ../research/scale-audit-2026-09-18/read_burst.py 100 off
```

Run only against an appropriate local/test database: read-only stress still
consumes real resources. Scripts select existing fixture accounts internally
without outputting credentials or issue contents. The profiler loads configured
plugin registries but does not run startup hooks. It is not a replacement for
the authenticated HTTP/browser acceptance test.
