# Team rosters and member selection — RADD-1115, 2026-09-10

Team details now search and render at most 50 effective members per window. Add-member selection opens a lazy, paginated person picker; it excludes every existing direct or inherited member before searching/counting/paging. The remaining full-research ledger is still active.

## Membership and authorization

Previously `member_users_with_via` loaded direct users, then independently walked each attached group's descendants and hydrated its full users before deduplicating in Python. Groups now owns a public SQL `member_projection` seam. Its recursive UNION deduplicates root/node/depth frontiers, handles cycles and diamonds without enumerating paths, and stops at the configured nesting depth, including direct membership at depth zero.

Teams owns the effective-member projection: union direct user rows and inherited rows, group by user ID, prefer direct provenance, otherwise choose the first carrier name in database order. The existing complete service readers reuse it, preserving their return shape and full-member semantics for leave, approvals and other consumers. `GET /teams/{id}/members` keeps an unpaged compatibility mode; the settings UI explicitly requests 50-row windows. Search matches literal, trimmed name/email text, and order has an ID tie-breaker. Count and window operate on the deduplicated relation, selecting only the roster wire fields.

The new `/teams/{id}/member-candidates` endpoint uses the existing owner/manager/global team-update guard, not user.manage. It offers active accounts under the existing public-directory source policy (service accounts retained; mail-provisioned requesters excluded), returning only ID/name. Neither security fields nor public email fields are added to this response. Full effective membership is excluded in SQL, including inherited people outside the current roster page. Existing membership mutation rules remain intact.

The roster provides loading, search-empty, errors, retry and last-page removal recovery. Removing a direct row that also has group membership immediately reveals its inherited provenance and removes the direct-removal action. The shared person picker gains a team-candidate scope and retry; nested focus and dismissal use the existing shared modal. Candidate choices remain selected until saved or cleared, independently of the roster filter. Team/member/role query metadata and team-member mutation prefixes cover the new windows.

## Verification

- [Focused PostgreSQL/HTTP tests](backend-focused.txt): **35 passed**. Includes depth 0/1/2/4 against the existing closure oracle on a cyclic diamond, 126-person paging, provenance and count parity, lean fixed-count query hydration, inherited candidate exclusion, source/active filters, delegated management, add/remove persistence, invalid paging/query inputs, and existing team/group/module contracts.
- [Full backend suite](backend-tests.txt): **2,402 passed, 4 skipped**, 98 warnings, 89.16 seconds, disposable database only.
- [Frontend checks](frontend-checks.txt): JavaScript regressions, host and all six plugin builds, real Chromium account/cancellation smoke passed. Runtime source Ruff and `git diff --check` pass.
- [Actual 126-member/126-candidate browser](browser.json): 50/50/26 traversal; inherited read-only rows; later-page persisted addition and candidate exclusion; direct removal revealing group membership; sole last-page row removal recovery; failures/retry; nested pointer/keyboard/Escape with retained unsaved team name at 390/768/1440 px. No captured console errors. Screenshots: [390](picker-390.png), [768](picker-768.png), [1440](picker-1440.png).
- [Previous five-actor Teams directory regression](team-directory-regression.json) passes with the new picker. It rechecks capability parity, off-page rename/create, transfer, deletion and focus. Its request recorder now handles URL objects and requires a nonempty capture; the old recorder could miss URL-object requests and vacuously pass its request-limit assertion. Other interaction assertions were independent of that recorder. Ownership selection now searches before selecting because the accumulated disposable fixture exceeds the shared select's visible option cap.
- [Populated roster API](live-roster-api.json): a 30-member team returns 3,824 bytes in 18 ms; 50 of 1,074 eligible candidates return 3,416 bytes in 12 ms. These are functional warm samples, not sustained-load measurements.
- [Populated roster browser](live-roster-browser.json) reaches two candidate windows and closes both nested dialogs without membership edits. [General populated browser](live-browser.json), [real LLM/search/storage probes](live-api.json) pass.
- [Development counts/schemas](development-data.json) remain 503,485 / `g1093ghost` and 8,923 / `d117pkg`. No populated issue/comment/membership content or schema was edited. Temporary sessions were revoked and files removed. Disposable server stopped; refreshed populated app serves port 18000 with workers disabled (PID 1523011 at this checkpoint).

## Reproduce

Run backend suites sequentially with the disposable `radd_audit_test` URL from AGENTS.md; pytest recreates that database. Run `npm run check` from `web/`. Start the disposable workers-disabled app on port 18001 only after the suite finishes.

From the repository root, seed then run:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-team-roster.py
node research/audit-2026-09-09/team-roster-browser.mjs
```

The browser owns revocation of the seed's private temporary session. To repeat the earlier team-directory regression, use its separate seed and browser scripts. For populated checks, run `live-check.py`, then `live-team-roster.py` and `live-team-roster-browser.mjs`, then `live-browser.mjs` to revoke the shared audit session. Never run the seed or pytest against populated databases.

## Remaining scope

P2 is not complete. Team ownership/manager selectors still load the public user catalog; group selectors, attached-group lists and role/project/page-space scopes remain unbounded. Other people/team readers, label/field automation registries, cycle axes/provisioning, legacy project scopes and authority-map scaling remain. Global group-sync realtime invalidation belongs to the remaining cache/delivery work; this evidence does not establish complete event coverage. There is no new migration, commit, push, release or hosted CI activation. All other research ledger requirements retain their scope.
