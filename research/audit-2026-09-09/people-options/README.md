# Automation people/team choices — RADD-1115, 2026-09-10

Verified local progress; [the full research ledger](../OUTSTANDING.md) remains active.

## Changes

Automation picker data no longer downloads the full admin user directory or hydrated team catalog. Auth and teams provide lean `/options` endpoints with search/count/pagination and exact saved-value lookup. Email choices require global `user.manage`; the public identity directory and its requester exclusions are unchanged. Active service and mail-requester accounts remain available to authorized administrative authors, matching the previous automation vocabulary. Inactive accounts are not new choices, but an existing saved address stays visible.

Team choices require `team.read` and return names without managers, stewardship checks or project capability hydration. Choice windows contain at most 50 rows in the browser and use the shared SQL projection pager.

Assignee/team controls preserve explicit token mode and clearing. Round-robin offers no invalid clear option. Notifications retain reporter/assignee role presets alongside paged email choices. Email recipients preserve outside addresses, contact roles and tokens; only the three role suggestions remain in their datalist. Changed-by conditions preserve legacy multi-values. Authors without user-management permission retain role and typed-recipient editing without fetching the private directory. Person rows show name above email for mobile readability.

## Verification

- [Full backend](backend-tests.txt): **2,391 passed, 4 skipped**. [Focused backend](backend-focused.txt): 11 cases covering owner options and module contracts. New tests exercise 126-row traversal, exact values, escaped/case-insensitive search, inactive-account filtering, source compatibility, limited credentials, public-directory email privacy and lean SQL projections.
- [Frontend](frontend-checks.txt): all JavaScript checks, host/all six plugin builds and actual HTTP account/cancellation browser checks pass.
- [Actual browser](browser.json): 126 people and 126 teams reached in 50/50/26 windows; later selections persist across assignee, team, round-robin, notify, send-email and changed-by controls. Saved inactive addresses, token/clear values, notification roles, arbitrary recipients and legacy values remain intact. Two delegated authors verify both sides of email-directory permission.
- No full `/users` or `/teams` requests occur in these editor flows; recorded option requests have limit 1 or 50. Other registries remain outside this claim.
- Actual blocked HTTP requests expose Retry and recover; mobile/tablet/desktop pointer input, modal bounds, keyboard focus and Escape pass with no captured console errors. Screenshots: [390 px](picker-390.png), [768 px](picker-768.png), [1440 px](picker-1440.png).
- [Previous catalog regression](automation-regression.json): all four project-owned catalogs, validation IDs, project keys, dry-run reset, mobile focus and retry still pass. Afterward only the user-row presentation changed; the full frontend check and people browser were repeated on that final presentation.
- [Populated endpoints](live-choices.json): 50 of 1,107 active accounts (4,706 bytes, 11 ms) and 50 of 2,296 teams (3,313 bytes, 6 ms). These are functional timing samples, not sustained-load measurements. No names/emails or credentials are saved in the endpoint evidence.
- [Populated API/LLM/storage/search](live-api.json) and [responsive browser](live-browser.json) pass. [Development counts/schemas](development-data.json) remain 503,485 / `g1093ghost` and 8,923 / `d117pkg`. All automation writes used the disposable database. Temporary sessions were revoked and cookie files removed.

## Reproduce

Run the backend suite with `RADD_TEST_DATABASE_URL` explicitly targeting the disposable `radd_audit_test`, and `npm run check` from `web/`. Wait for pytest before creating browser fixtures: it recreates its target database.

Start the workers-disabled disposable app on port 18001 serving `web/dist`, then from the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-people-options.py
node research/audit-2026-09-09/people-options-browser.mjs
```

The seed refuses other database names and creates seven disabled rules. The browser revokes both temporary sessions in cleanup. The earlier `seed-automation-options.py` / `automation-options-browser.mjs` pair reproduces the shared-control regression; run the fixture pairs sequentially.

## Remaining work

P2 remains open for label/field registries, other people/team readers and legacy project/page-space scopes. Teams settings still downloads the full catalog and filters it in the browser. Its API hydrates managers and stewardship per team; the list's global capability flags also need checking against the mutation guards, because it currently derives them from readable-project permissions. These are source-confirmed follow-ups, not completed load measurements. Cycle axes/planning/provisioning scans and authority-map scaling remain. All other design/product/operations ledger rows retain their scope. No migration, commit, push, release or hosted CI activation occurred.
