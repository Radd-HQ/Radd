# Cycle directories, item windows and visibility — 10 September 2026

This is local progress on **RADD-1115 / P2**, not completion of the whole research ledger. All write probes used `radd_audit_test`. No new migration is introduced by this slice.

## Changes

- Cycle name/status search, counts and 50-row windows run after team visibility in SQL. The sidebar, settings list and completion destination search use them. Completed drafts and incomplete legacy dates retain the existing status semantics.
- Completing a cycle requires an explicit destination; search reaches later cycles and preserves the chosen destination. Source and target visibility are enforced before writes. Create, edit/complete and delete controls use their respective permission atoms.
- Cycle item pages now fetch 50 rows at a time with server-side person/team/SLQ filtering. This removes the old ten-request/2,000-item cutoff and truncated client-side query intersection. Full-result progress and time totals use the same filters and item visibility rules. Person/team pickers query bounded directory windows instead of loading every account.
- Clearing or changing project/cycle filters resets the page, including a return to an earlier filter. Rows remain grouped by category within each page; group labels explicitly say how many are on that page.
- Cycle points, category and time aggregates require the caller's item permissions, including relation restrictions. Worklog totals stay in SQL and retain overrun/unestimated-item semantics.
- Velocity and burnup respect cycle visibility. Recent completed cycles are selected in SQL before rendering, and explicitly completed drafts without planned dates no longer crash velocity. Readers without the cycle catalog atom receive an empty velocity collection and their normal project scope; direct burnup reads still require the atom.
- Deferred release-pipeline imports remove a circular-import failure exposed by running focused tests independently of collection order.

## Browser evidence

Full backend suite: **2,375 passed, 4 skipped**, 72 warnings, 82.08 seconds. [Saved output](backend-tests.txt). HTTP regressions cover visibility before directory paging, hidden-cycle writes, permission-safe aggregates, hidden-cycle reports and undated completed cycles. The full frontend/plugin check passes; source Ruff and `git diff --check` pass.

[Actual backend/browser results](browser.json) and [frontend checks](frontend-checks.txt):

- 126 live cycles reached through 50/50/26 windows; 65 completed cycles through 50/15. Twenty team-hidden cycles never enter those results.
- Search finds a later completed cycle and a later sidebar cycle; empty search results retain their controls.
- An update-only reviewer sees edit/complete actions without create/delete actions. Completion remains disabled until a destination is selected. Choosing a later draft completes the empty source and starts the destination.
- A separate cycle has **2,105 synthetic issues**. The browser reaches all unique keys across **43 pages**, rendering at most **50 item rows**. Person/team filters and a bookmarked `priority = high` query each find the **105 issues beyond the previous cutoff**, with full-result totals. Clearing filters returns to the first page.
- Populated settings and item pages fit 390/768/1440 px without document overflow or captured console errors. Screenshots: [mobile directory](directory-390.png), [desktop directory](directory-1440.png), [mobile items](items-390.png), [desktop items](items-1440.png).

The initial paging probe clicked a disabled Next button during search debounce. It now waits for the control to become enabled and verifies the pointer hit. This was a probe timing defect; the later item cutoff and page-reset failures were application defects.

The [126-project regression](project-browser.json) also passes after the shared page-reset correction. [Populated-system API checks](live-api.json) pass against the 503,485-issue development database, including storage health, semantic search and a real vLLM SSE completion using synthetic text. [Development counts and schema versions](development-data.json) remain unchanged for both populated databases. These individual probes are not load or p95 measurements.

## Reproduction

Run backend tests before seeding browser fixtures: pytest recreates its database. From `server/`, use the disposable test URL documented in `AGENTS.md`. From `web/`, run `npm run check` (host, all plugin remotes, JavaScript regressions and browser smoke/cancellation).

Start the workers-disabled app against `radd_audit_test` on port 18001. From the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-cycle-directory.py
node research/audit-2026-09-09/cycle-directory-browser.mjs
```

The seed refuses any other database name. The browser revokes its temporary session and deletes its private cookie file. Fixtures remain only in the disposable database until the next pytest run.

## Remaining scope

P2 remains open for legacy cycle/project selectors, recurring-series readers, views, users, page-space/dashboard directories and authority-map scaling. This is functional paging verification, not a sustained load benchmark or a complete accessibility audit. Hosted CI, deployment activation and all other ledger rows retain their separate acceptance criteria.
