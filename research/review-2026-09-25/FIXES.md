# Corrections after the review

The app is preproduction with no production users. The review's demand for
compatibility migrations preserving retired implicit integrations is withdrawn.
New integration policies remain explicit and disabled until configured.

Implemented in the working tree:

- Preserve automation cause and silence through notification and SDK consumer
  planning/delivery, stopping auto-watch from restarting an automation chain.
- Render validation messages against the original draft with an `item.title`
  allowlist. Related-record findings retain their verdict but cannot quote those
  records in submitter feedback. Preserve separate advisory and required branches
  when converting shared legacy validation graphs.
- Refuse contributed actions with missing named outputs, recording a skipped
  plan. Per-item action rendering uses that invocation's item. Release previews
  show the candidate count and first 20 issue keys, and explain project-wide scope.
- Isolate Alertmanager fingerprints per receiver and serialize receiver delivery.
  A durable seed marker prevents deleted environment-seeded receivers reappearing.
- Completion email includes automated closures and all external thread contacts,
  excludes active internal users, and suppresses done-to-done and CSAT duplicates.
  A reusable entered-category gate is available. Current-state gates read subjects
  correctly even without an event snapshot.
- Filter plugin search by readable projects before limiting and scan additional
  candidates when row access checks narrow results. Milestone results link to and
  focus the specific milestone. Dispatch every matching contributed notification
  kind, including contributions to events also handled by core notifications.
- Show related automation rules and disabled templates in Email, VCS and
  Alertmanager settings. Supply repository-scoped VCS merge/release templates.
- Debounce dynamic node shape queries, declare shape-affecting parameters, bound
  caches and retain prior shapes while loading. Display the configured chain cap
  and retain declared optional payload paths after samples become available.
- Claim authenticated VCS webhook deliveries transactionally when an ID is
  supplied. Suppress repeated GitLab CI outcomes and ignore older pipeline runs
  or source timestamps. Rollbacks leave deliveries retryable.

Final verification: **3,099 backend tests passed, four skipped**, including 18
permanent regression tests in `server/tests/test_review_interactions.py`;
**33 frontend tests passed**. Host and milestone builds, milestone type checking,
Ruff on changed Python files, `git diff --check`, and browser smoke/setup/editor
checks passed. Browser
checks use the real built frontend with mocked API responses. Provider responses
and mail transport are stubbed in regression tests; live SMTP/provider delivery
has not been exercised.

Database changes are in `d1332review` and `d1333review`, after `d1321mirror`.
They are exercised by the normal isolated test database migration chain. They
have not been applied to the development application database. The corrected
`d1329verdict` conversion affects installations that have not run that migration;
it does not infer and rewrite ambiguous already-converted development graphs.

Delivery guarantees are deliberately bounded: the SDK consumer remains
at-most-once, and webhook replay protection requires a stable delivery ID plus
the same event/body. This is not a promise of exactly-once external delivery.

Reproduce the browser checks after building `web`:

```bash
cd web
node scripts/browser-smoke.mjs
node scripts/browser-review-interactions.mjs
```

The latter loads the current backend catalog in a separate Python process and
does not connect to the application database.

## Second-pass fixes

All 13 second-pass findings are addressed in the working tree:

1. Preview skips script gates explicitly; submission validation rejects them. Live script credentials are minted and revoked in independent transactions, so script execution never commits the caller's pending item or graph changes.
2. State-category gates take exactly one branch, testing all incoming items against their current states.
3. Execution accounts are bound to stable IDs. Missing/inactive accounts stop execution and record a failure. An authorized editor can explicitly adopt execution.
4. Webhooks authenticate the host before resolving its repository. Reference identity, CI, and mirrored time are isolated by connection. Shared active-host secrets are rejected as ambiguous.
5. Failed/refused actions stop their dependent path; unaffected paths remain independent. Failures are reported in node details, run status, history errors, and failure events.
6. The editor marks unsaved changes and sends its current draft for preview, including before the first save. Late preview/save responses cannot replace newer edits or annotate a different draft.
7. Preview accepts recorded event replay or a custom payload and project seed. Script branches and branches requiring created objects/action outputs explicitly say they were not simulated.
8. CI records separate reported streams, aggregates their states, orders runs/attempts/source timestamps, and suppresses repeats. Check/job notifications update badges; workflow/pipeline outcomes fire the CI trigger. The badge says “Reported CI,” not required-check approval.
9. Existing PR/MR associations continue receiving status/title/URL updates after a key is removed, including through backfill. Historical associations are retained deliberately.
10. A durable initialization marker prevents deleted environment-seeded connections from returning.
11. Only registered, enabled repositories ingest webhooks. Repository controls distinguish default release project, ingestion, cross-project linking, and time mirroring. Restricted scope also applies to CI/deployment triggers and backfill.
12. Settings support host editing and pause/resume. Blank credentials preserve existing secrets. Mutation errors and backfill unknown keys, unmatched authors, and partial errors are visible.
13. Email settings match relevant trigger/action combinations, not every rule subscribed to item updates. Policy counts distinguish enabled rules and state that rule conditions still apply.

The new migration is `d1334review`. It retains unambiguous legacy link/time origins; ambiguous legacy origins stay historical rather than being assigned to an arbitrary host. Its downgrade deliberately refuses to collapse connection-scoped data. No application database migration or deployment was performed.

Permanent regression coverage: `server/tests/test_second_review_interactions.py`, the connection-isolation case in `test_time_mirror.py`, and `web/scripts/browser-second-review.mjs`. The earlier defect-reproducing probes (`second_pass_probes.py`, `second-pass-browser.mjs`) were removed in RADD-1411 and remain in git history.

Live provider delivery and real outbound scripts are not exercised by the browser/regression fixtures. CI summaries concern received reports, and event replay uses current subject state rather than reconstructing a historical database snapshot.

Second-pass verification completed: the full backend run passed 3,116 tests and skipped four; its only two failures were exact CI-payload assertions that had not yet included the new workflow metadata. After updating those expectations, both tests passed on rerun (3,118 backend tests verified in total). The 18 new second-review regression tests passed as part of that full run. All 33 frontend tests, the host production build, Ruff on changed Python files, and `git diff --check` passed. Browser smoke, the first-review integration check, and the expanded second-review editor/VCS settings check passed against the built SPA with mocked APIs.
