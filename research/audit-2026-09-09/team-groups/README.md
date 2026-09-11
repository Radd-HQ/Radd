# Team group directories — RADD-1115, 2026-09-10

Attached-group lists and group selection now use 50-row server windows with name/DN search, explicit errors/retry and stable ordering. The picker excludes all held groups before count/limit. It works for team owners/managers without readable projects and shows both direct and nested member counts, directory paths and missing-group warnings.

## Changes

`teams.service.group_page` projects the public group fields and filters membership through SQL subqueries. `GET /teams/{id}/groups` preserves its unpaged compatibility mode; the UI requests 50 rows. `GET /teams/{id}/group-candidates` uses the existing team-management guard, rather than requiring the unrelated readable-project floor of the general group catalog. Internal `team_groups` stays complete so directory reconciliation continues to process every attached group.

`groups.service.transitive_member_counts` aggregates the shared depth-limited recursive member projection once for the requested window. Candidate reads select counts without hydrating all users or walking each group separately. The general `/groups` reader reuses that batch, and resolves parent/child names outside the current page. Previously those names became `?` under filtering/pagination. General group search now trims/escapes terms consistently and has an ID ordering tie-breaker and bounded query length; its existing authorization floor is unchanged.

The UI retains directory-missing warnings with semantic colors, last-page removal recovery and derived-roster invalidation after attachment changes. Candidate additions show errors inside the dialog and retain failures after closing it. A failed list has retry instead of masquerading as empty. Duplicate team/group invalidations were removed.

Directory reconciliation remains a global team-update operation because it changes shared directory membership. Delegated team owners/managers can edit attachments but are no longer offered a sync action that the endpoint refuses. Global operators see “Sync all attached groups”; a one-row presence query keeps this action independent of the visible search filter, with its own retry. No external LDAP reconciliation was invoked in these browser probes.

## Verification

- [Focused backend](backend-focused.txt): **26 passed**, including owner/manager/global/read/project-scope cases; 126 attached and candidate group windows; literal name/DN search and invalid inputs; missing flags; one transitive count query per candidate window; cross-page parent/child names; derived membership after add/remove; and full internal group reads for sync.
- [Full backend](backend-tests.txt): **2,416 passed, 4 skipped**, 107 warnings, 93.08 seconds against the disposable database. [Frontend checks](frontend-checks.txt) pass for JavaScript regressions, host plus six plugin builds and real Chromium account/cancellation checks. Runtime source Ruff and `git diff --check` pass.
- [Actual group browser](browser.json): 126 attachments and 126 candidates reached in 50/50/26 windows; held groups excluded; later nested group attachment/removal updates the member roster; missing-group warning and directory-path search; last-page recovery; retry; failed attachment remains visible after dialog dismissal. No full group-catalog request or unexpected HTTP/console error.
- [Mobile](picker-390.png), [tablet](picker-768.png), [desktop](picker-1440.png): nested pointer/keyboard/Escape behavior preserves the unsaved team name and restores focus, with bounded dialog content.
- [Roster regression](roster-regression.json) and [stewardship regression](steward-regression.json) exercise earlier team-detail work against the new group section.
- [Populated group API](live-groups-api.json): one attached group, one eligible candidate and two total mirrored groups. Functional samples return 195/210/516 bytes. These small real catalogs do not replace the 126-group fixture or establish sustained-load performance.
- [Populated group browser](live-groups-browser.json) verifies directory-path search, no full catalog read, unchanged attachments and a global sync control that stays available under unmatched search. [General populated browser](live-browser.json), [real LLM/storage/search checks](live-api.json) pass.
- [Data/schema record](development-data.json): 503,485 issues / `g1093ghost` and 8,923 / `d117pkg` unchanged. No populated issue/comment/group attachment content or schema was edited. Temporary sessions were revoked and files removed. Disposable server stopped; populated workers-disabled app remains on port 18000 (PID 1580673 at this checkpoint).

## Reproduce

Run backend tests sequentially with the disposable test URL in AGENTS.md, and `npm run check` from `web/`. Start the workers-disabled disposable app on port 18001 after tests finish. From the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-team-groups.py
node research/audit-2026-09-09/team-groups-browser.mjs
```

The browser revokes its private fixture session. Run earlier roster/stewardship seeds and browsers separately. Populated read-only sequence: `live-check.py`, `live-team-groups.py`, `live-team-groups-browser.mjs`, then `live-browser.mjs` to revoke the shared session. Never use a populated database as a pytest/seed target.

## Remaining scope

Role/project/page-space scope selectors and other directory consumers remain open, including global group readers that still request complete catalogs. General group adjacency arrays and legacy complete manager-ID payloads retain their compatibility contracts. Global group-sync realtime invalidation and actual background/external directory delivery are not verified by this checkpoint. All other P2 and broader research outcomes remain active. No migration, commit, push, release or hosted CI activation occurred.
