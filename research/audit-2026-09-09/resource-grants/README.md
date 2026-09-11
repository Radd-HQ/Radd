# Generic resource-grant management — 2026-09-10

RADD-1115 checkpoint: verified locally, not released. The full [research ledger](../OUTSTANDING.md) remains active.

## Changes

The grant editor now searches and renders 50-row windows, including expired grants that administrators need to replace. `/grants/directory` applies the registered resource-management gate before counting and paging in stable creation/ID order. Name projections cover only the current window and respect public-person, role, team, group and project visibility rules. Hidden names cannot be inferred through search totals. Existing complete, live-only authorization reads retain their contract.

The shared Add dialog loads subject and project choices on demand. Allow/deny rules, expiry, global and multiple-project scopes retain their semantics. Failed reads show retry rather than claiming unrestricted access; failed writes retain drafts. Revocation preserves unseen rows and recovers the last page. Query identities separate resource/search inputs, cancel obsolete requests and reuse placeholders only within the same identity. Grant changes invalidate the editor and affected resource queries.

Two additional authorization defects were found and corrected. Attachment ownership previously bypassed parent readership and credential narrowing when managing grants: parent readership is now mandatory, and scoped credentials must pass the parent attachment-write binding. Global field managers without issue readership previously received an empty field catalog; their existing global management permission now admits the definitions. Empty-scoped keys gain no bypass. Field/page/attachment copy distinguishes allow rules, deny rules and parent restrictions. Attachment controls are visible without hover and measure 32 × 32 pixels.

## Evidence

- [Full backend](backend-tests.txt): **2,466 passed, 4 skipped**, 148 warnings, 108.15 seconds. [Focused checks](focused-tests.txt): 26 passed; this focused run preceded the final field-catalog assertions, which are covered by the full run.
- [Frontend checks](frontend-checks.txt): JavaScript regressions, host plus six plugin remotes, responsive/account browser smoke and real HTTP autocomplete cancellation pass. [Query cancellation](query-cancellation.txt) includes resource/search/page identity and placeholder behavior.
- [Dedicated browser](browser.json): 126 grants across 50/50/26 windows, four 126-subject catalogs and 126 projects; persisted allow/deny, expiry and multiple scopes; protected names; retries; expired-row replacement; last-page recovery; page and attachment grant mutations; three nested dialogs with retained drafts/focus at 390/768/1440 px. One expected unsurveyed-item CSAT GET returned 404; no other unexpected HTTP failures were accepted.
- [Populated grant reads](live-grants.json), [read-only editor browser](live-editor-browser.json), [general browser](live-browser.json) and [API/LLM/storage/search](live-api.json) pass. The editor probe uses public person choices and makes no grant writes. The real catalog contains one builtin-field, two field and one view grant in the checked resources.
- [Environment](environment.json): populated databases remain at **503,485 / 8,923 issues**, schemas **g1093ghost / d117pkg**. Port18000 runs workers-disabled (PID1988641); port18001 stopped. Temporary sessions revoked and private cookie files removed.

Screenshots: [390 px](grant-people-390.png), [768 px](grant-people-768.png), [1440 px](grant-people-1440.png).

## Reproduction and remaining limits

Use the database safety/startup instructions in [AGENTS.md](../../../AGENTS.md). Automated tests and `seed-resource-grants.py` must run sequentially against **radd_audit_test only**. Build the frontend before starting the disposable app on port18001. The fixture script creates disposable actors/catalogs, page and filesystem attachment data, and writes its private session file under `/tmp`. `resource-grants-browser.mjs` consumes and revokes those sessions. Read-oriented populated checks run `live-check.py`, `resource-grants-live.py`, `resource-grants-live-browser.mjs`, then `live-browser.mjs`; the last probe owns session cleanup. Probe scripts are in this report's parent directory.

The bounded editor does not make its parent screens bounded: this browser records two full project reads from field settings and two full team reads from issue properties/comments outside grant-editor activity. Complete field catalogs, field scope selectors and project-scoped-only field-manager admission remain open. Internal project authority maps, service-account/key directories/counts, other legacy readers, page/template consumers and cycle scans also remain in P2. QueryObserver invalidation checks do not establish complete worker delivery or sustained-load performance. No real provider-policy writes, migrations, release, commit, push or hosted CI activation were performed.
