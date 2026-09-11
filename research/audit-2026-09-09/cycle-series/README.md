# Recurring-series settings — RADD-1115, 2026-09-10

Additional local progress on the full [completion ledger](../OUTSTANDING.md). P2 is still in progress.

## Implemented behavior

Recurring settings previously fetched/rendered every series and hid pending/error states as if no configuration existed. `cycles.directory.series_page` now applies escaped label search before count and stable label/id pagination. The router preserves `cycle.read` admission and returns `X-Total-Count`; omitted limits retain API compatibility. Browser requests use 50-row windows with debounced search, distinct keys and cancellation.

`SeriesSection` was separated from the cycle settings route. It has explicit loading, empty, failure and retry states. Deleting the only row on a last page returns to the preceding window. Saving adopts the server's returned next number after provisioning, avoiding a stale dirty form. Series events now invalidate the dedicated cache tag. Idle inputs follow refreshed data; unfinished local edits remain intact. The existing generic view/dashboard paging hook was extracted to `useDirectory` and reused.

## Verification

- [Full backend suite](backend-tests.txt): **2,385 passed, 4 skipped**, 81 warnings, 86.65 seconds. New PostgreSQL/HTTP coverage verifies stable complete windows, case-insensitive and literal-percent/underscore search, bounds, legacy unpaged parity, read-only write refusals and empty-scope credential admission/counts. Ordinary members receive baseline cycle-read permission; the refusal fixture uses an explicitly scope-limited credential.
- [Frontend checks](frontend-checks.txt): JavaScript regressions, host/all six plugin builds, account-switch smoke and actual HTTP cancellation pass. A real QueryObserver verifies series subscriptions and refetch after a simulated series event.
- [Actual browser](browser.json): 126 series reached in 50/50/26 pages, later search/empty recovery, save/reload, two provisioned cycles, returned next number, stop-recurring preservation of those cycles, 51-to-50 last-page deletion, blocked-request error and successful retry.
- Real API changes plus a **simulated WebSocket message** verify idle-input refresh and retention of an unfinished edit. This is deliberately not a browser-to-worker-to-browser delivery claim; workers were disabled.
- Pointer edits and control/document bounds pass at 390/768/1440 px; no captured console errors. Screenshots: [390](settings-390.png), [768](settings-768.png), [1440](settings-1440.png).
- [Shared-directory browser regression](shared-directories-regression.json) passes all four 126-entry catalogs, later pins/widget selections and mobile navigation after the paging-hook extraction. [Populated browser](live-browser.json) passes responsive navigation and nested unsaved-draft focus.
- [Populated API](live-api.json) verifies connected LLM SSE, semantic search and storage. [Recorded development data](development-data.json) retains 503,485 and 8,923 issues and the original schemas. All series/cycle fixture writes use the disposable database.

## Reproduce

Run the backend suite sequentially with `RADD_TEST_DATABASE_URL` pointing only to `radd_audit_test`, then run `npm run check` in `web/`. Start the app on 18001 with the disposable database URL, workers disabled and the current `web/dist`. From the repository root:

```bash
RADD_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5456/radd_audit_test \
server/.venv/bin/python research/audit-2026-09-09/seed-cycle-series.py
node research/audit-2026-09-09/cycle-series-browser.mjs
```

The seed refuses other database names. The browser revokes the temporary session and removes its private cookie file in cleanup. Do not run pytest or fixture writes against the populated databases.

## Remaining limits

Cycle axes/planning still consume a full catalog. Legacy project/user/team selectors, page-space directories and authority-map scaling remain P2 work. Internal series label matching and provisioning still scan existing series/cycles and need measurement/replacement without changing Unicode label/collision semantics. This slice adds no migration, sustained load result, release, hosted CI activation or full accessibility acceptance. Every other research outcome retains its ledger criteria.
