# RADD-1113 — bounded, permission-safe discussions

The full research goal is tracked by [OUTSTANDING.md](../OUTSTANDING.md), epic RADD-1112. This is one implementation slice, not completion of the whole goal.

Issue and wiki discussions use the new bounded feed (50 rows initially, at most 200 per API request). Older windows use exclusive `(created_at, id)` cursors and SQL audience filtering. An inserted newer comment or deleted cursor row cannot shift an older window. The existing full-list API remains a compatibility surface for SDK consumers; interactive readers use bounded pages. Migration `h1113commentpage` adds the parent/time/id index and replaces the redundant parent-prefix index.

The service now invokes the registered parent read gate for both legacy and feed reads. Wiki bindings also check inherited page restrictions. This closes a discovered path where a space/project read grant could expose a more narrowly restricted discussion.

`CommentHistory` keeps the reader's position while older rows prepend and lazy renderers settle, and releases anchoring immediately on user interaction. Wiki discussions and inline annotations have independent filters/cache identities, so a busy discussion cannot hide all its annotations. When the last older page removes the loading control, focus moves to the preserved comment without scrolling.

## Evidence

- Final full suite: **2,366 passed, 4 skipped**, 67 warnings, 78.28 seconds. [Backend output](backend-tests.txt).
- Six JavaScript test files, host/all six plugin remotes and Chromium smoke pass. [Frontend output](frontend-checks.txt).

- [Real-browser results](browser.json): all 125 issue comments, 125 wiki discussion comments and 55 inline annotations remain reachable. Reading-position deltas range from -0.40625 to +0.34375 px. No console errors.
- [Issue screenshot](issue.png) and [wiki screenshot](page.png), inspected from an isolated server on port 18001 against `radd_audit_test`.
- Backend regressions cover equal timestamps, hidden rows between pages, a deleted cursor, concurrent newer insertion, internal author/manager/team policy parity, restricted issue/wiki parents, separate inline windows, and HTTP limit/cursor validation.
- The temporary browser session is revoked in script cleanup. No populated development issue/comment content was modified.

Run `seed-discussion-check.py` only with `RADD_DATABASE_URL` naming `radd_audit_test` (enforced by the script), then serve that database on port 18001 with workers disabled and run `discussion-browser.mjs`. The browser script consumes and removes `/tmp/radd-discussion-session.json`; never put that credential in the report. Do not run pytest concurrently: its fixture recreates the same database.

## Remaining broader work

Reply/reaction behavior, directory scaling, full accessibility/device checks and production-scale load measurement remain separate ledger outcomes. The new pager bounds each request and initial rendering; deliberately loading every older page can still grow the browser's retained history. SDK/full-export callers can still request the legacy complete list; data portability work must preserve that use case or version its replacement explicitly.
