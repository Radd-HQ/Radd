# Sign-in starting access — local verification, 2026-09-10

RADD-1115 remains In Progress. This closes the starting-access editor slice of P2, not the complete directory or research ledger.

## Behavior and implementation

- `StartingAccess` mounts ten saved rule cards, with 50-grant and 50-team windows per card. Draft edits remain local until the provider is saved; paging never replaces the complete policy with the visible subset.
- `StartingRoleDialog` uses lazy role and project choices. `/roles/assignable/options` excludes Baseline before paging; Baseline already applies to everyone. Selected project IDs produce project grants; an explicitly empty selection produces a global grant. Duplicate scope pairs are avoided.
- Team choices share the lazy directory, disable already selected teams and preserve unseen saved IDs. Teams may include both directory groups and direct users; obsolete exclusion guidance was removed.
- `/sso/provisioning-references` accepts at most 100 IDs per catalog and projects only ID/name (project key) columns. The current browser window sends at most 50 per catalog. The existing credential-aware instance-admin guard protects this read-only POST. No role permissions, team managers or complete project catalog are hydrated.
- Query identities normalize reference ID sets, pass cancellation signals and carry role/project/team metadata. Real QueryObservers verify cancellation and name-frame invalidation; this is not full worker delivery evidence.
- `sso.registry.provisioning_rules` reads 126 rules and their children in three SQL statements instead of one plus two per rule. The complete policy contract is retained for provisioning and provider saves.
- Each grant/team application owns a savepoint. A recoverable SQL refusal no longer poisons the account transaction or discards subsequent valid grants/memberships. Existing domain matching, combined matching rules, existing-account linking and once-only account provisioning remain intact.
- Provider edit/issuer-check buttons have accessible names. Failed saves expose an alert and retain drafts. Project chips use the shared button kit.

## Evidence

- [Full backend](backend-tests.txt): **2,462 passed, 4 skipped**, 144 warnings, 107.01 seconds. Only `radd_audit_test` was used. [Focused](focused-tests.txt): 46 passed, including real duplicate-email SQL failures in both role and team applications, valid-rule survival, later-login non-reapplication, permission/scope gates and narrow SQL projection.
- [Frontend checks](frontend-checks.txt): JavaScript regressions, host/all six plugin remotes and Chromium account/cancellation smoke pass. Runtime Ruff and `git diff --check` pass.
- [Actual disposable browser](browser.json): 126 saved grants in 50/50/26 windows; 126 rules in ten-card windows; all 126 role/project/team choices reached; off-page rule edits; duplicate exclusion; global/project scope persistence; last-team-page recovery; blocked-name-read retry; failed-save recovery. Readback verifies 128 grants, 50 teams, unchanged domains and preservation of 124 untouched rules. Blank client-secret save preserves the actual synthetic stored secret and disabled provider state.
- Three nested dialogs retain focus/drafts and fit at [390](starting-projects-390.png), [768](starting-projects-768.png) and [1440](starting-projects-1440.png) pixels. Screenshots were visually inspected; no captured console errors.
- [Populated sign-in checks](live-starting-access.json): one real provider with zero provisioning rules; dialog opens/closes at all three widths without writes. Bounded catalogs cover 5 assignable roles, 99 projects and 2,296 teams. Reference projection resolves current windows. The absence of real saved rules is explicit: large-rule saves and provisioning outcomes use disposable data.
- [Populated API](live-api.json) and [general browser](live-browser.json): real vLLM SSE completion, semantic search, all three storage health probes and responsive issue/settings interactions pass. These are functional probes, not a load benchmark or an external OIDC callback test.
- [Environment](environment.json): development issue counts remain 503,485 and 8,923; schemas remain `g1093ghost` and `d117pkg`. Populated app runs workers-disabled on 18000, PID 1927923. Disposable app stopped; temporary sessions revoked and files removed. No migrations, commits, pushes, release or hosted CI activation occurred.

## Reproduce safely

Run the full backend suite from `server/` using the disposable URL specified in AGENTS.md. Wait for its process to exit before seeding: pytest drops/recreates that database. Run `seed-starting-access.py` against `radd_audit_test`, start the workers-disabled app on 18001 with the built web dist, and run `node research/audit-2026-09-09/starting-access-browser.mjs`. The browser revokes its temporary session and removes the private file. Do not seed or run suites concurrently against that database.

For populated checks, run `live-check.py` against the unchanged 5455 database and workers-disabled app18000, then `starting-access-live.mjs`, then `live-browser.mjs` (which revokes the shared temporary session). Do not enable or edit the real provider.

## Remaining scope

Provider APIs still return/save complete policies and the provider catalog; this slice bounds editor rendering and reference/catalog hydration. Rule application remains complete and may execute many valid grants at account creation. Generic resource grants, service-account/key directories and count aggregation, other remaining selectors/readers, page/template consumers, cycle scans and authority-map scaling remain open. Global event emission/delivery, sustained load and all design/product/operational ledger criteria retain their full scope.
