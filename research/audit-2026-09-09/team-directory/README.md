# Teams directory, authority and detail — RADD-1115, 2026-09-10

Verified local progress; [the full research ledger](../OUTSTANDING.md) remains active.

## Changes

Teams settings now searches the server in 50-row windows instead of downloading and filtering every team. Counts use the same trimmed/escaped search, and deleting the only row on the last page recovers the preceding window. The selected team opens in a shared modal and resolves directly by ID; new teams and renamed teams remain reachable independently of the current search. Authorized owners/managers/global administrators can rename a team through that detail.

Team reads now load managers once per requested window and derive stewardship from those rows. Global capabilities come from global effective permissions, matching the mutation guards. Previously a global team administrator with no readable project could be shown no edit/delete capabilities, while a project-scoped grant could advertise powers refused by the global guard. Owner/manager delegation remains per team, and limited credentials remain intersected. A refused catalog returns a zero count; the direct read requires `team.read`.

Create-only and delete-only administrators can reach Teams in settings. Delete no longer depends on eligibility to transfer ownership or appoint managers. Role-grant detail is not requested when its readable-project gate cannot succeed. An unconditional leave hook fixes a React hook-order hazard when transfer removes ownership controls from an open detail.

The nested managers picker now consumes Escape before the containing modal: closing suggestions restores input focus and preserves the rename draft; a subsequent Escape closes the detail. This works with focus on either the input or an option button. The existing shared picker remains the owner of that behavior.

## Verification

- [Before output](before-tests.txt) records the failing global/project capability cases and missing direct/window behavior. Owner/manager cases in that pre-change run fail at the newly required direct endpoint, not at their existing stewardship assertions.
- [Focused backend](backend-focused.txt): **20 passed**, including team delegation and module contracts. Five authority cases compare list/detail flags with actual rename/delete results; paged tests assert one manager query per 50/50/26 window, no project-catalog hydration, complete traversal, search/count parity and restricted reads.
- [Full backend](backend-tests.txt): **2,397 passed, 4 skipped**. [Frontend](frontend-checks.txt): JavaScript regressions, host/all six plugin builds and real HTTP account/cancellation checks pass.
- [Actual browser](browser.json): 126 catalog teams, 51 boundary teams and five delegated sessions. It verifies full traversal, search recovery, later-team rename, creation under unmatched search, manager-only membership edits, ownership transfer, delete-only UI, last-page deletion and HTTP error/retry recovery. Catalog GETs request 50 rows; the recorder observes methods separately from the legitimate create POST.
- Keyboard/pointer/modal bounds pass at 390/768/1440 px. Manager suggestions close before the team dialog; the unsaved rename survives that first Escape. Closing the dialog restores the directory trigger and does not save the draft. No captured console errors or unexpected HTTP errors. Screenshots: [390 px](detail-390.png), [768 px](detail-768.png), [1440 px](detail-1440.png).
- [Populated team API](live-teams.json): 50 of 2,296 teams, 10,787 bytes, 15 ms; one direct team read, 205 bytes, 4 ms. These are individual functional samples, not a load benchmark.
- [Actual populated team browser](live-team-browser.json) confirms 50 rendered teams and direct detail opening/closing without edits. [API/LLM/storage/search](live-api.json) and [responsive/draft-focus browser](live-browser.json) pass. [Issue counts/schemas](development-data.json) remain 503,485 / `g1093ghost` and 8,923 / `d117pkg`.

All rename/create/member/transfer/delete writes were confined to the disposable database. Populated checks changed temporary session metadata only. Temporary sessions were revoked and private cookie files removed.

## Reproduce

Run backend tests with `RADD_TEST_DATABASE_URL` explicitly targeting `radd_audit_test`, and `npm run check` from `web/`. Wait for pytest before creating fixtures; its setup recreates that database.

Start the workers-disabled disposable app on port 18001 serving current `web/dist`. From the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-team-directory.py
node research/audit-2026-09-09/team-directory-browser.mjs
```

The seed refuses other database names. For the populated app, run `live-check.py`, then `live-team-directory-browser.mjs`, then `live-browser.mjs`; the last script owns temporary-session revocation and cookie-file cleanup. The team browser performs reads only.

## Remaining scope

Team detail still uses full person/group/role-scope selectors and an unpaged membership roster; those are subsequent P2 work, not covered by the bounded team-catalog claim. Other legacy team/project selectors, label/field registries, page-space directories, cycle axes/provisioning and authority-map scaling remain. Broader accessibility, design/product work, sustained load, background integrations, upgrade/export and hosted CI outcomes retain their ledger criteria. No migration, commit, push, release or hosted CI activation occurred.
