# View and dashboard directories — RADD-1115, 2026-09-10

Saved local verification; the full [completion ledger](../OUTSTANDING.md) remains active.

## Behavior

View/dashboard queries apply readable-project admission and live hierarchical share authorization in SQL before counting, ordering or limiting. The shared access service owns the grant predicate, including exact-level denials, nested groups, expiry and intrinsic ownership. Hydration runs only for the requested window. Legacy unbounded API calls remain compatible.

Sidebar global views, project views, queues and dashboards use server search and 50-row windows. Pins and opened views resolve by ID; project landing and legacy roadmap redirects request one matching view. The saved-view widget chooser searches the complete visible catalog. Obsolete frontend full-catalog view/dashboard query factories were removed. Search remains focused after clearing the input.

## Evidence

- [Backend suite](backend-tests.txt): **2,384 passed, 4 skipped**, 80 warnings, 88.08 seconds. New SQL-policy parity tests exercise 180 rows per resource, 126 visible, across direct/team/nested-group grants, expiry and denials; 50/50/26 windows, escaped search, project/type filters and hidden direct lookup. Hydration never exceeds 50 rows in these page checks.
- [Frontend checks](frontend-checks.txt): JavaScript regressions, host and all six plugin builds, account isolation and actual HTTP autocomplete cancellation pass.
- [Real directory browser](browser.json): all 126 entries reached in each of four catalogs, 20 private entries excluded per catalog, later-page navigation, pin/reload/current-view context, widget persistence/count link and legacy redirects. All catalog GETs use limits of 1 or 50. Empty-search recovery and retained input focus pass.
- Responsive navigation passes at 390/768/1440 px with no console errors. Screenshots: [390](navigation-390.png), [768](navigation-768.png), [1440](navigation-1440.png).
- [Populated API](live-api.json) and [browser](live-browser.json): real LLM SSE completion, semantic search, storage health, responsive navigation and nested unsaved-draft focus pass. [Development counts/schemas](development-data.json) remain unchanged: 503,485 and 8,923 issues. Fixture writes were confined to the disposable database.

## Reproduce

Run the full backend suite with `RADD_TEST_DATABASE_URL` pointing only at `radd_audit_test`, then `npm run check` from `web/`. Start a workers-disabled app on port 18001 against that disposable database. Run `seed-shared-directories.py` with its database URL, then `node research/audit-2026-09-09/shared-directories-browser.mjs` from the repository root. The browser consumes and revokes the private temporary session created by the seed. Do not run the seed or pytest against either populated database. The separate populated probes use the read-oriented commands in AGENTS.md.

## Remaining scope

P2 still includes cycle axes/planning, recurring series, legacy project/user/team selectors, page-space directories and authority-map scaling. Windowed view/dashboard responses still carry full definitions; lean projections, grant-change invalidation and measured payload/startup budgets remain follow-ups. These functional checks are not a sustained load test, full accessibility acceptance or release. No new migration, commit, push or hosted CI activation was performed.
