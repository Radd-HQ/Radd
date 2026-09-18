# Scale optimization implementation

Implemented in the workspace on 2026-09-18, against audited revision `1ce62ae`.
The original audit files remain the baseline. No production deployment was
performed. The additive search-index migration was applied to the local audit
database and is included for other installations.

## Changes and behavior contract

- **Permission SQL:** group projects with identical item-read relations before
  compiling row guards, for both work-item and search queries. The actor,
  restricted-row guard, participant rules, and project boundaries still apply.
  PostgreSQL JIT and application pool settings remain unchanged.
- **List hydration:** load page project records and field scopes in batches,
  share field/builtin grants across the page, and reuse resolved project
  permissions. Instance administrators skip field-grant reads they already
  bypassed. Member field restrictions still use project-specific subjects.
- **Board cells:** expose the project predicate on the outer ranked query as
  well as the authorized subquery, so a project board need not scan global
  ranks to find its next cards. Counts, sort order and cursors remain intact.
- **Search:** indexed case-insensitive key prefixes and numeric prefixes;
  limit ranked full-text candidates before reading preview text; omit unused
  search vectors/comment bodies from ORM results; reuse the readable-project
  map. A full key-result page skips FTS that cannot contribute a displayed hit.
  Ranking, snippets, numeric completion, and access filters retain their rules.
  No new alias-search behavior or approximate candidate cutoff was introduced.
- **Large ID inputs:** bounded queries for item loading, estimates, epic refs,
  history, descendant frontiers and time totals. Complete results are retained;
  there is no silent truncation at a batch boundary.
- **SLA worker:** keyset iteration of active project items in batches of 500,
  preserving first-match policy selection. Terminal timers are skipped before
  loading refs; remaining refs load in batches instead of once per issue.
  This bounds working batches; it does not make the entire sweep incremental
  or shorten its transaction to one transaction per batch.
- **Reports:** cycle/SLA reports narrow authorization to their actual candidate
  IDs instead of materializing every visible issue first. History reconstruction
  retains compact timelines while releasing full event snapshots per batch.
  Historical totals and calendar/timer calculations are unchanged.
- **Directory grants:** expand effective team/group membership in batched SQL,
  including nested directory groups, instead of per-team/per-group reads.
- **Issue loading:** state choices, field definitions, screen layout and field
  writability start alongside the project read. The detail mounts after these
  initial requests settle. Field controls do not optimistically become editable
  before the writability response. Existing shared summary caches stay fresh
  for 30 seconds and relevant permission events invalidate them.
- **People and quick actions:** show existing selected names from the full issue
  immediately; fetch people choices when the picker opens and quick-action
  catalogs when editing starts. A cold picker can briefly show “Loading people”.
  All prior choices remain available, including external reporters and the
  existing project-access grouping. Pointer and keyboard opening share the path.
- **Rich text:** keep the readable placeholder until the asynchronous renderer
  has populated its DOM, preserving the viewport deferral and same rich-text
  engine. This removes the raw-text → empty → rendered interval; it does not
  promise zero layout movement when differently formatted content replaces text.
- **Edit/realtime traffic:** ordinary scalar PATCH responses now include row
  capabilities, seed the complete detail and avoid an immediate duplicate GET.
  Assignment, visibility, relationships and other non-scalar edits retain the
  read-access recheck, as do responses from older servers without capabilities.
  Collections still refetch for membership
  and ordering. Exact detail/transition websocket interests are authorized in
  batches; safe record-local events skip unrelated details. Coalescing unions
  changed IDs into one signal per project/entity instead of emitting one frame
  per record. Configuration, permission, structural and unknown events remain
  broad. Text edits remain broad because they can create/remove mention links.
  No timing-based suppression hides concurrent writers' events.

## Validation

The backend suite runs against its automatically recreated disposable test
database, never the 501k-issue audit database. Regression coverage includes:

- Original per-project permission predicates versus grouped predicates across
  public/member/reporter/admin/own-only actors and 100 additional project scopes.
- More than 65,535 input IDs, duplicates, missing IDs, complete results across
  batch boundaries, worker page sizes, and canonical batched ref equivalence.
- Exact realtime scope authorization, denied-ID fallback, revocation/structural
  refresh, and retaining all changed IDs while coalescing a burst.
- Single-project and batched field scope parity.
- Existing item/search/participant visibility, grants, report, SLA, bulk,
  group/team membership, board and cursor suites.

The production frontend build and Node tests are checked. A new synthetic HTTP
browser fixture is included in `npm run test:browser`; it verifies permissions
resolve before field controls mount, selected names appear before directory
requests, picker opening fetches choices, selection saves and rechecks access,
scalar edits display the response without an immediate detail GET, summary requests are deduplicated,
and rich-text initialization has no blank frames. Existing browser checks cover
responsive layout, search cancellation, and account-switch cache isolation.

- Full backend suite: **2,820 passed, 4 skipped**. The initial run identified
  a missing optional dependency declaration for realtime → items; it was fixed
  and the entire suite rerun successfully.
- Additional final scale/SLA regressions: **8 passed**, including terminal
  timers skipped before ref loading and breaches emitted only once across batches.
- Final reporting check: **9 passed**, including a new regression ensuring
  malformed filters are still rejected when there are no completed cycles.
- Frontend Node suite: **26 passed**; production build and all three browser
  checks passed. Build retains the existing CSS highlight/chunk-size warnings.
- [Response comparison](read-result-parity.json): admin/member cross-project
  lists and exact/lowercase/numeric-key search outputs match byte-for-byte after
  canonical serialization. Common-word searches preserve the ordered rank and
  updated-time pairs and identical data/snippets for shared hits. They are not
  byte-for-byte identical: the existing search order has **no final tie-breaker**.
  Rows tied on both rank and timestamp can reorder or exchange places at the
  LIMIT boundary. [Repeated old-query runs also vary](search-tie-diagnostics.json).
  The optimization retains those ordering rules; it does not establish a new
  deterministic tie order or promise identical selections within an equal tie.

## Measured results on the local 501,298-issue dataset

All 24 final service operations completed successfully. These are single diagnostic
observations, not latency percentiles; they exclude HTTP/browser/worker delivery.
See [baseline](read-profile-validated.json) and [after](read-profile-after.json).

| Operation | Admin before → after (ms) | Member before → after (ms) | Admin SQL before → after | Member SQL before → after |
| --- | ---: | ---: | ---: | ---: |
| issue detail | 241 → 230 | 243 → 145 | 29 → 25 | 38 → 38 |
| project list 25 | 37 → 33 | 180 → 91 | 30 → 26 | 37 → 37 |
| cross project list 25 | 97 → 34 | 275 → 70 | 115 → 27 | 66 → 37 |
| project list offset 20000 | 103 → 101 | 148 → 119 | 31 → 27 | 20 → 20 |
| project state summary | 229 → 212 | 204 → 203 | 5 → 5 | 16 → 16 |
| cross project state summary | 493 → 320 | 8390 → 257 | 4 → 4 | 14 → 14 |
| cross project assignee summary | 351 → 626 | 7959 → 260 | 5 → 5 | 15 → 15 |
| project state cell 25 | 64 → 74 | 1946 → 235 | 32 → 28 | 49 → 49 |
| all visible count | 106 → 106 | 1143 → 117 | 4 → 4 | 8 → 8 |
| search issue key | 211 → 30 | 883 → 54 | 6 → 5 | 19 → 15 |
| search word render | 1218 → 971 | 2505 → 846 | 6 → 5 | 19 → 15 |
| report visible id universe | 1539 → 1705 | 1311 → 245 | 4 → 4 | 8 → 8 |

Not every individual observation improved: the admin assignee summary was slower
in this run (351 → 626 ms), and all-visible admin ID materialization still costs
about 1.7 seconds. These paths are not reported as resolved. Member offset-20k
reads return zero rows and are not comparable to the admin 25-row result.
The report-universe probe intentionally exercises the old broad seam; actual
cycle/SLA report callers now pass their candidate IDs to avoid that whole universe.

### Issue-page requests

The same anonymous cold navigation to `/issues/PUBPRF-73` made **40 → 34 API
requests**, including the application shell, with no browser errors in either
trace. The three eager people-directory requests are gone, and project/page-space
summaries each load once instead of twice. Field writability remains one batched
request, not one request per field. See [before](issue-comments-public.json) and
[after](issue-comments-after.json). These single browser traces are request-count
evidence, not a repeated interaction-latency benchmark; independent optional
sections still load separately.

### Synchronized read bursts

The same configured pool (5 + 10 overflow), JIT default/on, same sampled member,
and mix of 50 detail / 30 list / 10 search / 10 summary operations were used.
No other audit/test process was running against PostgreSQL during these bursts.

| Run | Success | Median | p95 | Pool acquisition p95 | Wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Before](read-burst-100.json) | 94/100 | 16.02 s | 33.68 s | 27.11 s | 41.04 s |
| [Before repeat](read-burst-100-jit-on.json) | 95/100 | 15.75 s | 34.69 s | 26.56 s | 41.28 s |
| [After](read-burst-100-after.json) | 100/100 | 4.04 s | 7.47 s | 6.35 s | 8.40 s |
| [After repeat](read-burst-100-after-repeat.json) | 100/100 | 3.99 s | 7.50 s | 6.29 s | 8.42 s |

After-run event-loop lag p95 was 98 / 69 ms; maximum 440 / 407 ms. This is a
substantial improvement, but a 7.5-second p95 synchronized burst still includes
considerable queueing. It is **not** the audit’s sustained 100-person mixed
read/write workload or a hardware sizing result. The old failures hit the
probe’s 15-second SQL guardrail; production did not have that timeout configured.

### Permission output and large batches

[The after diagnostic](scale-diagnostics-after.json) returned the same canonical
summary hash as the original audit with JIT on and off:
`54099db4e28fe572cf2e23d1ee5fa2de5809dae4d20d095c368d5f72e53848a8`.
The original 100,864-ID item fetch that failed at the PostgreSQL parameter ceiling
now returns all 100,864 records. The helper still returns a full dictionary by
contract; the SLA engine uses the new bounded iterator instead.

## Reproduction

From `server/`:

```sh
.venv/bin/alembic upgrade head
.venv/bin/pytest -q
.venv/bin/python ../research/scale-audit-2026-09-18/profile_reads.py ../research/scale-audit-2026-09-18/read-profile-after.json
.venv/bin/python ../research/scale-audit-2026-09-18/compare_read_results.py
.venv/bin/python ../research/scale-audit-2026-09-18/diagnose_scale.py ../research/scale-audit-2026-09-18/scale-diagnostics-after.json
.venv/bin/python ../research/scale-audit-2026-09-18/read_burst.py 100 default ../research/scale-audit-2026-09-18/read-burst-100-after.json
```

From `web/`: `npm test`, `npm run build`, and `npm run test:browser`.
Read-only profiles still consume resources; run against an appropriate test
instance. The response comparison uses the audited builders with current
service seams; it checks compatibility, not clean old-build throughput.

## Remaining scale work

This implements the directly testable optimizations above, not every proposed
architecture change in the audit. It does **not** certify 100 active users.

- SLA sweeps still visit the project; persisted next-evaluation deadlines and
  incremental timer state require migration/rebuild/replay validation.
- Reports still reconstruct histories and retain compact per-item timelines.
  Mature-history projections, indexed related-event access and retained-history
  capacity testing remain necessary for intensive reporting.
- Badge counts for distinct queries still execute separately. Arbitrary SLQ
  collection invalidation remains conservative; dynamic membership must stay live.
- Broad search still ranks every authorized FTS match. Large directories are
  deferred on issue opening but their current picker endpoint is still unpaged.
- Bulk writes still call the full authorization/event pipeline. Same-project
  creation lock duration, rare global rank rebalance, and deep-roadmap membership
  growth have not been redesigned.
- Query/admission budgets, cancellation at PostgreSQL, worker isolation,
  connection sizing and high-frequency custom-field indexes require the actual
  deployment/workload. No blanket timeout, approximate count, pagination change,
  virtualized interaction or background-job workflow was introduced.

The next acceptance step remains the audit's sustained **100 distinct users,
mixed browsing/search/editing**, with realistic history, active SLAs, live
websockets and isolated outbound delivery sinks. Hardware is still undecided.
