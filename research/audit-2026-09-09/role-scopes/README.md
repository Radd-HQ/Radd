# Role grants and scope choices — RADD-1115, 2026-09-10

RoleGrantsSection now loads 50 grants at a time. Role, project and wiki-space choices use lazy server search/paging, preserving selections made on other pages and individual grant mutations. Existing global/project/space wire semantics and complete legacy API readers remain supported.

## Implementation

`auth/grant_directory.py` owns `/role-grants/directory` for user/team/group subjects. It counts/orders/windows grant rows in SQL before hydrating names, including expired rows. Names respect their own catalog policy: role names require role.read; project keys use the shared visible-project resolver, including actual own/team/participant relationships; space labels pass through the existing GrantScopeSpec registry only after space-read filtering. Hidden scopes remain present as unlabeled grant IDs, as in the old grant API, without exposing their names or mislabeling them Global. No auth-to-pages model dependency was introduced.

`/roles/options` returns ID/name/key without permission definitions and supports exact ID or builtin-key lookup. `/page-spaces/options` returns ID/name/slug without pages or counts. Search, total and limit apply to the authorized SQL projection. Both honor credential scope and revocable read permissions. The existing public project picker supplies project choices. Full authority maps remain a separate scaling concern.

The grant dialog is separated from its list component. Three builtin presets resolve directly; selections across project/space pages persist as chips and a readable scope sentence. Empty project and space sets explicitly mean global scope. Role replacement uses PATCH on the same grant ID; revoke uses DELETE on one ID. Neither replaces unseen grants. Expired grants are shown as expired. A final-page deletion recovers the preceding window. Read and mutation failures stay visible, and read failures offer retry. Scope/role/project metadata tags describe the new queries; broad cache convention consolidation remains in M2.

The team access inspector's empty message now says it confers no permissions through role grants. An empty permission union does not prove there are no grant rows; the earlier message incorrectly asserted that.

## Verification

- [Focused backend](backend-focused.txt): **26 passed**, including all three subject types, 126 grants and stable tie-breaking, expired retention, permission-safe labels, actual owned-issue project visibility, role.read revocation, hidden-space exact lookup, 126-role/space traversal, literal search, lean fields, scoped/empty admin keys, invalid inputs, module contracts and route order. Includes the prior wiki scope-security regressions. The focused run was repeated after giving all fixture grants an identical creation timestamp to verify tie ordering explicitly; runtime code was unchanged.
- [Full backend](backend-tests.txt): **2,435 passed, 4 skipped**, 119 warnings, 96.14 seconds against the disposable database. [Runtime source/diff checks](source-checks.json) pass.
- [Full frontend checks](frontend-checks.txt): JavaScript regressions, host and all six plugin UI builds, actual HTTP cancellation and account-switch browser checks pass.
- [Actual browser](browser.json): all 126 grants, roles, projects and spaces reached in 50/50/26 windows; later role change preserves grant ID/scope and other rows; two projects plus two spaces persist as four correct grants; builtin preset lookup; expired display; final-page revoke leaves the other 50 grants; list/choice failure and retry. No unexpected HTTP or console errors.
- [390 px](picker-390.png), [768 px](picker-768.png), [1440 px](picker-1440.png): three nested dialogs retain viewport bounds, keyboard focus, chosen role and unsaved team name. Escape restores the parent control before dismissing the containing draft.
- [Populated options](live-options.json): six roles (499 bytes), six spaces (535 bytes) and two sampled team grants (721 bytes). [Populated role/scope browser](live-browser.json) confirms reads and cancellation leave existing grants unchanged. These small real catalogs do not replace the 126-entry fixture or prove sustained-load performance.
- [Real LLM/storage/search](live-api.json) and [general populated browser](live-general-browser.json) pass. [Both development databases](development-data.json) retain 503,485 / 8,923 issues and `g1093ghost` / `d117pkg` schemas. Temporary sessions were revoked and their files removed. Disposable server stopped; workers-disabled populated app remains healthy on port 18000, PID 1655062 at this checkpoint.

The initial browser probe assumptions were corrected to match the existing project ordering and wait for enabled preset controls. The final probe asserts all expected identities and actual persisted records. It also records the remaining full wiki-space reads instead of incorrectly attributing those shared shell/permission-hook requests to the new grant controls.

## Reproduce

Run backend suites sequentially using the disposable test URL in AGENTS.md; run `npm run check` from web/. After tests finish, start a workers-disabled disposable app on 18001, then from the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-role-scopes.py
node research/audit-2026-09-09/role-scopes-browser.mjs
```

For the populated workers-disabled app on 18000, run `live-check.py`, `live-role-scopes.py`, `live-role-scopes-browser.mjs`, then `live-browser.mjs` to revoke the shared session. Never pass either populated database as the pytest/seed target.

## Remaining scope

The shared shell and `usePermissions` still request the complete wiki-space catalog (seven reads over repeated team-panel mounts in this browser journey). The new grant controls add no full catalog reads during scope selection, but the application-wide dependency is not resolved. Next: wiki permission summary, paged sidebar/index and direct space lookup, then remaining directory readers, role administration, label/field registries, legacy project scope pickers, cycle scans and full authority-map scaling. Legacy complete grant APIs remain for compatibility and other consumers. Grant cache/invalidation, accessibility/localization, load testing and every other full research criterion stay active. No migration, commit, push, release or hosted CI activation occurred.
