# View/dashboard share authorization — 10 September 2026

This additional defect was found while tracing the remaining **RADD-1115 / P2** directory readers. It is fixed locally; view/dashboard paging and the wider research ledger remain open.

## Findings and changes

Both share loaders explicitly requested expired grants. Their duplicated grant-level loops also treated every matching row as an allow, ignoring the grant's `effect`. An expired co-owner could therefore retain authority until cleanup, and a deny-owner row could confer co-ownership.

The loaders now use the shared live-grant filter. `access.service.shared_resource_level` delegates to the existing hierarchical resolver for direct users, teams and transitive directory groups. Public access is a fallback level governed by the same exact-level deny rule. Intrinsic ownership remains with the resource owner; denying one level does not erase a separately allowed level.

Legacy `shares` payloads and sharing indicators contain only live allow grants. This matters because the legacy editors reconcile positive invitations: presenting a denial as a co-owner invitation could let an unrelated sharing edit remove it. The full generic `/grants` API still carries deny/expiry policy. Richer grant-management UI is not claimed by this fix.

## Evidence

- [Before](before.txt): all six HTTP cases reproduced expired access on the disposable PostgreSQL database, covering views/dashboards × direct user/team/nested group.
- [Full backend suite](backend-tests.txt): **2,382 passed, 4 skipped**, 78 warnings, 84.86 seconds. `test_shared_resource_grants.py` exercises the ASGI application with a real PostgreSQL session. It advances only the grant loader's clock to the exact expiry boundary, preserving the actual row and avoiding reliance on a sweeper.
- The regression checks directories, direct dashboard reads, view counts, edit/delete/sharing and grant-management gates. It verifies live co-ownership, loss of access at expiry, denial without accidental elevation, retained viewer access, public-editor denial and intrinsic owner management. Deny rows stay outside the legacy invitation payload.
- The old view/dashboard test fixtures now create their own readable project. Five focused tests previously relied on a project committed by another module; the focused suite passes independently (**21 passed**).
- Source Ruff and `git diff --check` pass. No frontend source changed during this authorization fix; the [cycle-selector frontend/build/browser evidence](../cycle-selectors/README.md) remains applicable.
- [Read-only development counts/schema checks](development-data.json) remain **503,485 / g1093ghost** and **8,923 / d117pkg**. No populated issue content or schema was changed.
- The populated app was refreshed on port 18000 (PID 1284977), workers disabled, health 200. [API/storage/search/real-vLLM probes](live-api.json) and [responsive/nested-focus browser regression](live-browser.json) pass with no captured console errors. Temporary sessions were revoked and cookie files removed. Port 18001 remains stopped.

## Reproduce

From `server/`, with no other suite or fixture app using the disposable database:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd \
RADD_TEST_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
.venv/bin/python -m pytest -q tests/test_shared_resource_grants.py \
  tests/test_deny_precedence.py tests/test_view_sharing.py tests/test_dashboards.py
```

Pytest drops/recreates its selected test database. Never select either populated `radd` database.

## Remaining work

View/dashboard directory pagination must apply ownership, live allow/deny rules, public fallback and transitive subjects before count/limit. Their present full-list loading is still P2 work. The broader ledger's design, localization, recovery, load, portability and hosted CI requirements are unchanged. No commit, push, release or CI activation occurred.
