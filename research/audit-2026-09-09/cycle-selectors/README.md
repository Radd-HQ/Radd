# Cycle selectors and modal layering — 10 September 2026

Local progress on **RADD-1115 / P2**. The full research ledger remains open. All editable fixtures used the disposable `radd_audit_test` database; no migration was added by this slice.

## Behavior

`CycleSelect` and `CycleChoices` replace complete cycle downloads in issue creation/detail, bulk assignment, context menus, form defaults, automation actions, workflow conditions, dashboard widget configuration and burnup reports. Opening a picker searches the authorized catalog in 50-row windows. Closed ID selectors resolve only their current selection; name-based consumers retain the existing wire format. Multi-value workflow conditions preserve their selected IDs and display names. Automation clearing retains the explicit `none` sentinel.

Burnup choices filter out undated cycles before counting/paging. The default report requests one cycle with server-side active-first/recent ordering; a fixed-cycle widget bypasses that default lookup.

Real pointer testing exposed a shared modal defect: the bulk toolbar's backdrop filter established a containing block for its fixed-position descendants. Its nested picker appeared in the toolbar and could not receive clicks at the expected viewport coordinates. `Modal` now renders through a body portal. `IssuePanel` uses the same portal level so opening order determines which dialog is above the other. Existing dismissal and focus ownership are preserved in both directions: form → issue peek and issue peek → cycle picker.

## Verification

- [Backend suite](backend-tests.txt): **2,376 passed, 4 skipped**, 72 warnings, 92.03 seconds. The added dated-cycle regression verifies visibility and ordering before the limit; the full suite includes earlier credential, workflow, cycle and report permission checks.
- [Frontend checks](frontend-checks.txt): seven JavaScript test files, host and all six plugin remotes, account-switch browser smoke and real HTTP autocomplete cancellation pass. Source Ruff and `git diff --check` pass.
- [Actual backend/browser results](browser.json): 126 choices reached in 50/50/26 windows; later cycle selections persist through issue creation/detail, bulk assignment, context-menu clearing, form defaults, multi-value workflow conditions and automation actions. Automation clear saves `none`. Burnup offers all 46 dated fixture cycles, saves a later completed cycle and switches the ordinary report from its one-row default.
- The picker stays above the issue peek at **390/768/1440 px**, receives real pointer input, fits the viewport, recovers from empty search, keeps keyboard focus in the top dialog and closes with Escape while preserving the issue peek. Screenshots: [mobile](picker-390.png), [tablet](picker-768.png), [desktop](picker-1440.png). No captured console errors. Recorded cycle directory requests use limits of 1 or 50.
- [Populated browser regression](live-browser.json) passes after the portal changes, including unfinished form → issue peek → preserved draft, mobile navigation/settings and issue actions. [Populated API checks](live-api.json) pass for ordinary reads, storage health, semantic search and real vLLM SSE completion with synthetic text. [Read-only database counts/schema checks](development-data.json) remain **503,485 / g1093ghost** and **8,923 / d117pkg**.

Intermediate probe failures used nonexistent workflow/automation GET URLs and clicked React Flow before its fit animation settled. The final probe uses the actual read routes and waits for stable node bounds; these probe corrections are distinct from the verified application modal defect.

## Reproduce

Run the backend suite before seeding: pytest recreates its selected test database. Use only the disposable URL documented in `AGENTS.md`. Run `npm run check` from `web/`, then start a workers-disabled app against `radd_audit_test` on port 18001. From the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-cycle-selectors.py
node research/audit-2026-09-09/cycle-selectors-browser.mjs
```

The seed refuses other database names. Fixtures remain disposable; the browser revokes its temporary session and removes its private cookie file in cleanup.

## Remaining scope

Cycle-grouped/planning view axes still enumerate the complete cycle catalog to preserve empty groups, regex filtering and custom ordering. Recurring series, legacy project selectors, other directory families and authority-map scaling remain P2 work. Ordinary boards/lists no longer fetch the cycle catalog merely for context-menu assignment.

This is functional and responsive verification, not sustained load, full accessibility acceptance or release evidence. The context menu's missing menu-item/keyboard semantics remain part of V1. Hosted CI, product design, localization, account recovery, portability and every other open ledger row retain their acceptance criteria.
