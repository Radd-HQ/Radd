# Project context and selectors — RADD-1115, 2026-09-10

Verified local progress; [the full ledger](../OUTSTANDING.md) remains active.

## Changes

Workflow, issue-type, screen, access, release, form and time-logging settings previously downloaded all projects to find the one supplied by their route. They now use the direct project query and expose loading/error/missing states. Settings navigation uses the existing complete permission summary instead of another full-list union.

`ProjectSelect` resolves its current ID directly and opens the shared `ProjectPicker` only when needed. The picker searches the whole authorized catalog in 50-row windows, shows the selected row and supports explicit retry. Widget selectors preserve required vs optional project choices and the empty-string All-projects value. Bulk move filters destinations by `item.create` **on the server before pagination**; individual move guards remain authoritative. The chosen project object supplies the success message; the summary keeps the existing more-than-one-project affordance rule.

## Evidence

- [Browser results](browser.json): all seven settings routes resolve a later project directly with no unbounded project GET. Delegated management works; a release persists in the intended project.
- 126 writable, 20 read-only and 20 hidden project fixtures exercise 50/50/26 picker windows. Widget choices include readable projects and exclude hidden ones. Clearing All projects and selecting a later project persist the existing wire values. Required report-widget selection also saves successfully.
- Bulk move reaches all 126 eligible destinations, excludes read-only/hidden projects, moves an issue to the later project and preserves its old-key alias.
- Nested pointer selection, keyboard focus and viewport bounds pass at 390/768/1440 px; actual blocked search shows an error and Retry recovers. No captured console errors. Screenshots: [390](picker-390.png), [768](picker-768.png), [1440](picker-1440.png).
- [Focused backend checks](backend-focused.txt): **15 passed**, project directory visibility/summary/direct lookup and bulk move/rollback guards. This slice changes no backend runtime code; the latest full backend run remains **2,385 passed, 4 skipped** in [the previous checkpoint](../cycle-series/backend-tests.txt).
- [Frontend checks](frontend-checks.txt): JavaScript regressions, host/all six plugin builds and real HTTP account/cancellation smoke pass.
- [Populated browser](live-browser.json): responsive navigation and nested unsaved-draft focus pass on the development app. [Counts/schemas](development-data.json) remain 503,485 and 8,923 issues with the original schemas. Only temporary session metadata changed on the populated system; all release/widget/move writes were confined to the disposable database. The previous connected LLM/storage/search evidence remains valid; those paths were not modified in this slice.

## Reproduce

Run `npm run check` from `web/`. With no other fixture or test process using the disposable database, run the project-directory, bulk and bulk-move-guard pytest files with `RADD_TEST_DATABASE_URL` explicitly set to `radd_audit_test`. Start a workers-disabled app against that database on port 18001 using the built `web/dist`, then from the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-project-selectors.py
node research/audit-2026-09-09/project-selectors-browser.mjs
```

The seed refuses other database names. The browser revokes its temporary session and removes the private cookie file in cleanup.

## Remaining work

P2 is still open for other legacy selectors/multi-project scopes, user/team/page-space directories, cycle axes, provisioning scans and authority-map scaling. In particular, `ActionsBuilder.usePickerData` loads every project and starts separate state/release reads for each; `ValidationFields.useTargetOptions` does the same for types/forms. These are confirmed source-level request-fan-out paths, not a measured concurrency result. They need bounded, lazy choices without dropping off-page values. Startup/load budgets, design/product work and every other ledger requirement remain open. No commit, push, migration or hosted CI activation was performed.
