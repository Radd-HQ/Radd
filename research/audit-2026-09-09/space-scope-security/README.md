# Wiki scope security — RADD-1115, 2026-09-10

Tracing the remaining role/page-space selectors exposed three permission defects. They are corrected locally; directory pagination itself remains outstanding.

## Corrections

- Wiki batch permissions now delegate to the public `authz.permissions_for_spaces` seam. It matches direct checks for active status, admin authority, requester-specific floors, live global/space grants and API-key intersection. Project-only keys cannot borrow page permissions from their account.
- Unscoped page-template listing filters by readable spaces plus global templates in SQL. Reading one space no longer reveals every other space's template bodies. An explicit space still requires direct page-read permission; no readable spaces returns an empty list.
- Page creation resolves a template only within the destination space or global scope. Naming a template from another space returns 404 before any page is inserted. Local/global templates and placeholder rendering remain supported.

The duplicate pages-side permission resolver was removed. Auth owns principal policy; pages retains its public access facade. Internal complete template reads retain their existing contract. No schema migration or frontend runtime change was needed.

## Evidence

- [Before fixes](before-fixes.txt): 12 failing and 2 passing database/HTTP regressions reproduced policy divergence, hidden template disclosure and cross-space application.
- [Focused final checks](backend-focused.txt): permission parity, actual restricted-key/requester HTTP reads, forbidden-space refusal, no partial page creation, permitted/global rendering, existing template tests and module contracts.
- [Full backend](backend-tests.txt): **2,430 passed, 4 skipped**, 111 warnings, 93.83 seconds on the disposable database. Subsequent changes only improve formatting and expand the equivalent role-row query expression; focused checks were repeated afterward. Runtime Ruff and diff whitespace checks pass.
- [Existing identity parity](live-parity.json): all 12 identity/scope combinations match direct permissions over all six real wiki spaces. The probe uses a read-only transaction, existing admin/staff/requester accounts and request-only scope objects; it creates no keys or grants.
- [Populated wiki browser](wiki-browser.json): the six-space index and actual space tree open with no console or HTTP errors. This database has **zero templates**; template isolation/rendering evidence comes from populated fixtures in the disposable database, not this empty live template catalog.
- [Populated API](live-api.json): real connected LLM completion, semantic search and all three storage hosts pass. [Responsive browser](live-browser.json): 390/768/1440 px navigation, mobile settings/issue controls, nested focus and preserved unsaved draft pass without console errors.
- [Development data](development-data.json): issue counts remain 503,485 / 8,923, schemas remain `g1093ghost` / `d117pkg`. Temporary browser session revoked and private cookie file removed. Workers-disabled populated app is healthy on port 18000, PID 1612762 at this checkpoint. No disposable server was started for this slice.

The frontend bundle is unchanged from the [group-directory full frontend/plugin checks](../team-groups/frontend-checks.txt). These checks do not establish sustained load performance or worker/external integration delivery.

## Reproduce

Use the disposable test URL from AGENTS.md, sequentially:

```bash
# From server/, with the safe test environment exported:
.venv/bin/python -m pytest -q tests/test_space_permission_batch.py tests/test_page_templates.py tests/test_module_contracts.py
.venv/bin/python -m pytest -q
```

For the workers-disabled populated app, run `live-space-scopes.py` with its database URL. Run `live-check.py`, then `live-wiki-scope-browser.mjs`, then `live-browser.mjs` to revoke/remove the shared temporary session. Never point pytest at either populated database.

## Remaining work

RoleGrantsSection still eagerly loads grants and role/project/page-space catalogs. Bounded selectors, permission-safe labels, remaining directories, the full authority map and all other research ledger rows remain active. No commit, push, release, migration or hosted CI activation occurred.
