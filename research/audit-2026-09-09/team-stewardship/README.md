# Team ownership and manager selection — RADD-1115, 2026-09-10

Ownership and manager controls now load one saved-manager window and search candidates lazily. They no longer fetch the full public user directory. Existing managers can be promoted to owner; removing a manager edits only that person, preserving off-page and inactive managers.

## Behavior and seams

- `/teams/{id}/stewardship` returns one lean owner record and a count plus name/ID-ordered manager window. Saved inactive people retain their names and an inactive marker. Only ID/name/active are selected; account security fields are not hydrated for these reads.
- `/teams/{id}/steward-candidates?purpose=manager|owner` searches/counts before limit/offset and returns ID/name. Both candidate modes retain active public-directory account vocabulary, including service accounts and excluding mail-provisioned requesters. Current owners are excluded. Manager appointment also excludes existing managers; ownership transfer intentionally includes them, matching the backend's existing promotion semantics.
- Reads and writes use the existing intrinsic-owner/global-team-update guard. A manager may administer membership but cannot delegate or transfer authority. Project-scoped update and delete-only credentials cannot use stewardship endpoints. Missing user.manage does not prevent a legitimate owner from using the controls.
- Individual manager POST/DELETE operations preserve unseen managers. Appointments remain capped at 50; existing larger sets produced by transfers/legacy data remain pageable and individually removable. The old full-set PUT contract remains available. Transfer still retains the previous owner as a manager and removes the promoted person's redundant manager row.
- Manager add/remove, replacement and transfer serialize on the team row. Ownership routes acquire/refresh that row before checking the owner guard. Concurrent appointments cannot pass the capacity check together and exceed the limit.
- The shared person picker carries team and candidate-purpose query identity, request cancellation, error/retry and nested focus behavior. Manager-list removal recovers a now-empty last page. An unavailable list shows an error and retry, not a false empty state. Owner names, inactive saved manager names and away markers remain visible.
- Transfer cancels the old stewardship read before updating the direct team cache. If the current actor becomes a delegate, the invalidation excludes their now-forbidden stewardship read; rename/membership controls remain, ownership controls disappear, and the toast uses the selected person's name.

## Evidence

- [Focused backend](backend-focused.txt): **33 passed** including six credential/ownership cases, 126 saved-manager windows, 126 candidate windows, inactive retention, promotion and previous-owner refusal, source/search/validation checks, legacy off-page removal, and two actual concurrent database transactions competing for the last appointment slot.
- [Full backend](backend-tests.txt): **2,410 passed, 4 skipped**, 101 warnings, 89.49 seconds against the disposable database.
- [Frontend checks](frontend-checks.txt): all JavaScript regressions, host plus six plugin builds, real Chromium account/cancellation checks pass. Runtime source Ruff and `git diff --check` pass.
- [Actual stewardship browser](browser.json): 126 manager choices traversed in 50/50/26 windows; later selection persists while preserving an inactive manager; 51-manager legacy list paginates and recovers after last-page removal; promotion of an existing manager retains prior owner and inactive delegate without a forbidden refetch; saved-read and candidate errors retry successfully. No captured console errors or unexpected HTTP failures.
- [390 px](picker-390.png), [768 px](picker-768.png), [1440 px](picker-1440.png): nested ownership picker receives pointer/keyboard input, stays in bounds and preserves the containing unsaved team name on Escape.
- [Roster regression](roster-regression.json) and [five-actor directory regression](directory-regression.json) pass. The latter now exercises manager/ownership dialogs and waits for their loaded controls; the shared TokenMultiSelect fix remains unchanged for its other consumers.
- [Populated API](live-steward-api.json): 50 of 1,103 eligible people for each purpose, 3,416 bytes, 5/4 ms in this warm sample. A direct owner/empty-manager read returns 113 bytes. These are functional samples, not load measurements.
- [Populated stewardship browser](live-steward-browser.json) traverses two pages in each selector, confirms no full user-directory request and verifies unchanged owner/manager IDs. [General populated browser](live-browser.json) and [real LLM/storage/search probes](live-api.json) pass.
- [Development data](development-data.json) retains 503,485 issues at `g1093ghost` and 8,923 at `d117pkg`. No populated issue/comment/ownership/manager data or schema was changed. Private temporary sessions were revoked and files removed. The disposable server is stopped. The refreshed populated app runs workers-disabled on port 18000 (PID 1549344 at this checkpoint).

## Reproduce

Run backend suites sequentially using the disposable test URL in AGENTS.md, then `npm run check` in `web/`. Start the disposable workers-disabled app on port 18001 after tests finish. From the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-team-stewardship.py
node research/audit-2026-09-09/team-stewardship-browser.mjs
```

The browser revokes its private fixture session. Repeat roster/directory regressions with their respective seeds and browsers. For read-only populated checks, run `live-check.py`, `live-team-stewardship.py`, `live-team-stewardship-browser.mjs`, then `live-browser.mjs` to revoke the shared session. Never use populated databases as pytest or seed targets.

## Still outstanding

Group selectors/attached-group lists and role/project/page-space scopes remain unbounded. Other people/team readers, label/field automation registries, cycle axes/provisioning and authority-map scaling remain in P2. Legacy `TeamRead.managers` retains its complete ID array for compatibility; this change bounds displayed names and search, not every legacy payload. Global group-sync invalidation and every other full-research ledger outcome remain open. There is no migration, commit, push, release or hosted CI activation in this checkpoint.
