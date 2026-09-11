# Project directory progress — RADD-1115, 2026-09-10

This completes the project index/sidebar/creation-picker slice of P2 locally. P2 remains open for other directory consumers and representative scaling measurements.

## Implemented

- Project directory API supports name/key search, bounded limit/offset windows, optional permission and related-project filters, and total counts. Visibility is decided before filtering/pagination. Legacy clients can still omit a limit while they are migrated.
- `/projects/summary` returns visible-project totals, related counts and the complete permission union. `/projects/{id}` and `/projects/by-key/{key}` resolve direct links through the same visibility policy.
- The shared authorization batch reads project IDs instead of hydrating every project body. It still constructs an authority map proportional to project count; this is not a constant-time database-work claim.
- Projects index, sidebar and the new-item project picker render one 50-row window, with server search and previous/next controls. Search remains available after zero matches. Create choices are filtered by authority on the server before paging.
- Shell permissions/navigation use the summary. Issue/project route lookup, view project context and pinned project labels use direct reads. A current route project outside the sidebar page appears separately and retains expansion; a hidden related project remains directly accessible.

## Evidence

`backend-tests.txt`: full PostgreSQL suite **2,370 passed, 4 skipped**, 69 warnings, 77.73 seconds. New tests cover hidden rows preceding visible rows, stable ordering with timestamp ties, all 55 allowed projects across pages, restricted direct reads, literal wildcard search, last-page create authority, related-only hiding without access loss, HTTP bounds/counts and SQL evidence that permission summaries do not hydrate project bodies.

`frontend-checks.txt`: seven JavaScript test files, host plus six plugin remotes, Chromium account isolation/search cancellation and autocomplete cancellation pass. `browser.json` and `projects.png`: actual FastAPI/Postgres browser journey on the disposable database with 126 visible projects, pages of **50 / 50 / 26** and no duplicates. Search reaches later projects and recovers from no matches; create authority held only on project 124 enables the button before that page loads and yields exactly one picker choice. A direct issue and off-page current-project navigation work. 390/768/1440 px checks pass without horizontal document overflow; no captured console errors.

The browser resource records show actual project-directory request sizes/durations with `limit=50`. These are functional browser samples, not a sustained-load p95 benchmark. The seed and browser scripts are `../seed-directory-check.py` and `../directory-browser.mjs`; the seed asserts the disposable database name. The browser revokes and removes its temporary session after verification.

## Remaining P2 work

Views, cycles, users, page spaces and dashboards still have complete-list readers. Several settings/form/bulk-action selectors and the command palette still use legacy `projectsQuery`; migrate them using bounded search plus selected-record resolution, not a truncated substitute for a complete list. The cycle item query also has a ten-page cap and needs proper server filtering/pagination. Benchmark authority resolution and endpoint/query/payload work at representative scale. These are tracked in `../OUTSTANDING.md` and RADD-1115.

The two populated development databases retain **503,485 / 8,923** issues at **g1093ghost / d117pkg**. No test writes target them. The development server on localhost:18000 has been refreshed with this API; its background workers remain disabled.
