# Project-scoped builtin-field grants — 2026-09-10

RADD-1115 checkpoint: verified locally, not released. The full [research ledger](../OUTSTANDING.md) remains active.

## Behavior

Builtin-field grant writes already accepted project authority, but both grant readers required a global management check and the editor had no project context. Scoped field managers therefore could not inspect or manage their existing grants through settings.

Both `/grants` and `/grants/directory` now accept `project_id` or `global_only`. The registered resource hook authorizes the requested scope before reading; SQL applies the scope filter before search/count/paging. Selecting a project returns only grants saved in that project, excluding global and unrelated rows. Combining the two filters is invalid. No-parameter reads retain their complete legacy contract. Authorization reads remain live-only, while management windows include expired rows for cleanup/replacement.

Field settings distinguishes global builtin management from project management and offers bounded field.manage project choices without requiring issue readership. Global managers can choose All scopes, Global only or a project; project-only managers must select an authorized project. The editor explains that global grants may also apply without exposing their subjects or counts.

The chosen context participates in request/cache identity, resets paging and prevents previous-context placeholder rows. Grant creation from a fixed global/project context sends only that scope; all-scope creation retains multiple project selection using field-authorized choices with readable project labels. Subject catalogs keep their independent permission gates. Existing mutation checks continue to intersect account authority and API-key scopes before writing.

## Verification

- [Full backend](backend-tests.txt): **2,477 passed, 4 skipped**, 158 warnings, 113.41 seconds. [Focused](focused-tests.txt): 30 passed; the subsequent full suite covers the final preservation of legacy list ordering. Runtime/new-test Ruff and `git diff --check` pass.
- [Frontend/plugin checks](frontend-checks.txt): JavaScript regressions, host plus six plugin remotes, responsive/account smoke and real HTTP cancellation pass. Cache tests distinguish all/global/project contexts and reject previous-project placeholders; a real QueryObserver verifies scope-change request cancellation.
- [Dedicated browser](browser.json): 126 project choices without issue readership; 126 grants in 50/50/26 windows with expiry retained; 51-row boundary revocation; project switch and paging reset; failed reads/retry; fixed-project deny creation; global-only creation; complete all-scope view and multi-scope-capable creation with named field-authorized choices. HTTP readback verifies no change to the other project's 126 grants. No unexpected HTTP failures or captured console errors.
- Nested grant/subject dialogs preserve drafts and keyboard focus at 390/768/1440 px. Screenshots: [390](grant-dialog-390.png), [768](grant-dialog-768.png), [1440](grant-dialog-1440.png); the 390 px image was visually inspected.
- [Populated projections](live-grants.json): the existing builtin grant appears in the all-scope and matching project reads, while the global-only read is empty. Scope choices return 50 of 99 projects. [Populated scope browser](live-scope-browser.json) exercises all/global/project context and responsive choices without policy writes; readback preserves the existing grant. [General browser](live-browser.json) and [real LLM/search/storage/API](live-api.json) also pass.
- [Environment](environment.json): both development databases retain **503,485 / 8,923 issues**, schemas **g1093ghost / d117pkg**. Populated app18000 runs workers-disabled, PID2264010, health200. Disposable app18001 stopped; temporary sessions revoked and private files removed.

## Reproduce and continue

Follow [AGENTS.md](../../../AGENTS.md) for database safety and startup. Run pytest and fixture seeding sequentially against **radd_audit_test only**. After the complete frontend build, run `seed-builtin-grants.py`, start the workers-disabled disposable app on port18001, and run `builtin-grants-browser.mjs`. The probe revokes its fixture sessions. For populated checks run `live-check.py`, `builtin-grants-live.py`, `builtin-grants-live-browser.mjs`, then `live-browser.mjs`; the last probe owns the shared session cleanup. Scripts are in this report's parent directory.

Next: complete selected-field option/legacy registry readers, issue properties/comment team catalogs, service-account/key lists/counts and other P2 directories/scans. Builtin target/access validation and field deletion event-catalog registration still need review with the wider registry/event contracts; this change preserves existing validation semantics. Full worker delivery/load, authority-map scaling and every broader design, accessibility, recovery, portability and CI requirement remain open. No migration, commit, push, release or hosted CI activation occurred.
