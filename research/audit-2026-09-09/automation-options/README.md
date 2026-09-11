# Automation option directories — RADD-1115, 2026-09-10

Verified local progress. [The full research ledger](../OUTSTANDING.md) remains active.

## Behavior

Opening an automation previously fetched every project and then separate state/release catalogs for each project. Validation targets repeated the same pattern for issue types/forms. The builders now open lazy, searchable 50-row choice windows, backed by lean owner endpoints that return only value, label and a project-key hint. Authorization precedes filtering, deduplication, count and pagination. Form choices additionally require `form.manage`; ordinary readable projects do not expose their form configuration.

State names and release versions deduplicate before pagination. Free text remains available for template tokens, future vocabulary and explicit clearing values. Type/form targets retain UUIDs and project disambiguation, with exact selected-value queries limited to one row. Project selectors explicitly preserve either keys or IDs. The dry-run panel requests one default project and uses the paged project chooser for changes. The editor also stops requesting the admin user directory when its author lacks `user.manage`.

## Evidence

- [Backend suite](backend-tests.txt): **2,389 passed, 4 skipped**. [Focused checks](backend-focused.txt): nine cases including module contracts and four resource parameterizations covering permission-filtered windows, hidden projects, restricted credentials, form-management exclusions, duplicate names, escaped search, exact selected values and invalid limits.
- [Frontend checks](frontend-checks.txt): JavaScript regressions, host and all six plugin builds, responsive account-switch smoke and actual HTTP query/autocomplete cancellation pass.
- [Actual browser](browser.json): all four catalogs traverse 126 visible choices in 50/50/26 windows. Fixtures also include 20 hidden projects and 20 readable projects without form-management rights. Later choices persist through state/release actions, field-change conditions, validation targets, create-item and search-project scopes. Templates, future names, legacy multi-values and clear values round-trip. Changing the dry-run project clears the old seed search and sends the next lookup with the selected project ID.
- Request evidence asserts that opening the action downloads no owner catalog or unauthorized user directory. Project and option requests use limits of one or 50; no per-project state/release/type/form catalog requests occur. Other global registries remain outside this bounded-request claim.
- Pointer selection, modal bounds, focus trapping/restoration and Escape pass at 390/768/1440 px. A blocked request shows Retry and recovers through empty and matching searches. No captured console errors. [390 px](picker-390.png), [768 px](picker-768.png), [1440 px](picker-1440.png).
- [Populated option endpoints](live-choices.json) return 50 of 109 state names, 50 of 783 issue-type references, two forms and an empty release catalog. Recorded warm samples are 12–19 ms and 2–4,138 bytes; these are functional probes, not sustained-load measurements.
- [Populated API/LLM/storage/search](live-api.json) and [responsive browser](live-browser.json) pass. [Development counts/schemas](development-data.json) remain 503,485 / `g1093ghost` and 8,923 / `d117pkg`. Automation writes used only the disposable database; populated checks changed temporary session metadata only.

## Reproduce

Run the full backend suite with `RADD_TEST_DATABASE_URL` explicitly targeting `radd_audit_test`, then `npm run check` from `web/`. Do not run pytest while browser fixtures are in use: its fixture drops/recreates the test database.

Start a workers-disabled app on port 18001 against `radd_audit_test`, serving the current `web/dist`. From the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-automation-options.py
node research/audit-2026-09-09/automation-options-browser.mjs
```

The seed refuses other database names. It creates a delegated automation editor, project-owned choices and six disabled rules. The browser revokes its temporary session and removes the private cookie file in cleanup.

## Remaining scope

P2 remains open: user/team/label/field registries are still eager in parts of the automation UI; the authorization map still scales with total project count. Other legacy project scopes, page-space directories, cycle axes/planning and provisioning/name-matching scans remain. All other design/product/performance/operations ledger rows retain their acceptance criteria. No migration, commit, push, release or hosted CI activation was performed.
