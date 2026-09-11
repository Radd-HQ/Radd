# Radd application review — 9 September 2026

Radd has the foundations of a capable free issue tracker. Its strongest qualities are its feature breadth, modular backend, shared editor, and integrated service desk. Its immediate weaknesses are authorization gaps, inconsistent client caching, unfinished pagination, and a desktop-oriented shell. I would invest the next release in reliability and everyday usability before expanding the feature catalog.

Reviewed commit: `fec4c092`, plus the working tree. The existing change to `CLAUDE.md` was left alone. This review adds research artifacts only; it does not fix application code or change a running instance.

**Evidence and limits.** This is a broad repository audit with selected executable checks, not a line-by-line certification of every module. I inspected source, configuration, tests, deployment workflows, and the supplied board/issue screenshots. I built the current frontend and rendered it in Chromium with synthetic API responses. No local API or Postgres was running, and Podman failed because its overlay storage configuration was incompatible with the backing filesystem. Consequently, the full database suite, migrations, actual import/restore flows, production response times, and authenticated end-to-end workflows remain unverified. Security reproductions below use isolated services with mocked persistence; no real credentials or records were created.

## Structure and features

| Area | Current structure | Assessment |
|---|---|---|
| Backend | FastAPI, async SQLAlchemy, PostgreSQL, Alembic; 54 module directories including installable modules | A modular monolith is a suitable deployment model for a self-hosted tracker. |
| Kernel | Plugin loader, contribution registries, entity hosts, permissions, tasks, events and extension specifications | There is a real architecture here, with enforceable boundaries. |
| Frontend | React, TypeScript, TanStack Router/Query, Tailwind semantic tokens | Appropriate foundation; feature composition and caching conventions need tighter enforcement. |
| Editor | Milkdown/ProseMirror with custom React chrome, CodeMirror and diagram support | Sharing the editor across issues and pages is valuable; maintaining custom behavior carries a substantial browser-testing obligation. |
| Extensions | Python SDK, frontend plugin SDK, native ESM remotes, colocated module UI builds | Useful differentiation, but a large compatibility surface for a small maintainer team. |
| Operations | Compose, container build, Helm, backup/restore, monitoring and release workflows | Much stronger than a project that treats self-hosting as an afterthought. |

The measured source footprint is 103,281 Python lines in 655 backend files, 92,917 frontend lines in 508 TypeScript/TSX/CSS files, and 48,747 Python test lines in 197 files. These are physical lines, including comments and blank lines, and exclude dependencies and generated frontend output. There are 164 migration files. Size alone is not a defect, but this is already a substantial maintenance commitment.

Features are present in code for projects, epics/issues/subtasks, configurable workflows, custom fields, labels, saved views, boards, lists, planning, roadmaps, queues, cycles, releases, worklogs, dashboards, reports, bulk actions, cloning, merging and kind conversion. The service desk includes forms, requester access, mail intake/replies, SLAs, canned responses and CSAT. Wiki spaces provide page trees, versions, links and rich content. Authentication includes local accounts, TOTP, OIDC, LDAP and API keys. Optional AI, MCP, importers and integrations are substantial implemented subsystems, although their production behavior was not exercised here.

## Findings to address first

Priority means **P1: security or trust boundary to fix before broader adoption**, **P2: meaningful correctness, usability or scaling problem**, and **P3: maintainability or product refinement**.

### 1. P1 — Scoped API credentials can escape their scope

`POST /tokens` requires an authenticated user, then calls `create_api_token`. That service validates the requested scope but does not constrain it by the scope of the credential making the request. Omitting `scopes` creates an unscoped token, even when the caller arrived with an empty or narrowly scoped API key. The new credential carries the account's full authority; it does not exceed the underlying account, but it defeats the restriction placed on the original key. Expiration inheritance also needs review.

There is a second escape path: backups, plugin management and instance scoped-settings check `instance_role` directly. An admin's narrowly scoped PAT still passes these checks because they never consult `token_scope`.

**Evidence:** `server/src/radd/modules/auth/router.py:669`, `auth/service_tokens.py:34`, `auth/deps.py:53`, `backup/router.py:45`, `pluginmgr/router.py:23`, and `settings/router.py:24`. The isolated reproduction supplied an empty-scoped admin principal: token creation produced `scopes=None`, and both the backup and plugin admin guards accepted the principal.

**Fix:** Make credential delegation an explicit policy. Either require a human session for credential management, or enforce that child keys cannot exceed the caller's scope or lifetime. Route privileged operations through a scope-aware authorization seam that preserves the instance-admin requirement. Test both personal PATs and service-account keys through real HTTP authentication, including an empty scope and an admin account with a read-only key. Also test revoking/listing other keys and the other self-service account endpoints.

### 2. P1 — Merge skips the per-item update restriction

`merge_items` checks project-level `ITEM_UPDATE`, then starts moving comments, attachments, watchers, worklogs and other rows. `authz.require` intentionally accepts qualified permissions such as `item.update@own`; the individual service must subsequently enforce the relationship to each item. Normal update and conversion do that. Merge does not call `ensure_item_relation` on either source or destination.

**Evidence:** `server/src/radd/modules/items/service/merge.py:117`, `auth/authz_core.py:318`, and `items/service/core.py:169`. An isolated run retained the real `authz.require`, supplied `item.update@own`, and used a source unrelated to the actor. Merge returned successfully after issuing 37 SQL statements to a mock session. This proves the missing service gate; a real database/HTTP regression is still required.

**Fix:** Enforce update relationships on both records before any move. Check restricted state/parent changes and the visibility implications of moving internal content across projects. Treat merge as a privileged composite operation with explicit invariants, not just several SQL updates following a project permission check.

### 3. P1 — Logout retains the previous account's cached data

Logout removes only the `['auth','me']` cache family, then navigates within the same SPA. Login invalidates that family again. Project, issue, comment and other account-dependent queries remain cached under keys that generally do not include the authenticated identity. A subsequent user in the same tab can receive previous cached results while their own requests run; permission-bearing project/space data also remains available in the cache.

**Evidence:** `web/src/components/shell/UserMenu.tsx:33`, `routes/login.tsx:56`, `lib/queries/items.ts`, and `lib/queries/projects.ts`. In the built browser app, a synthetic private item remained readable from the actual QueryClient after executing the logout cache-removal operation. I did not run a complete two-user session against a backend.

**Fix:** Clear or replace the account-scoped QueryClient on identity changes and terminate the old account's live connection. Cancel requests and pass their AbortSignals through the API wrapper; it currently exposes no signal option. Audit persisted recents, drafts and preferences for data that should be namespaced by user. Add an A → logout → B regression with different project access.

### 4. P1 — Login has no application throttling and blocks the event loop while hashing

Local login and TOTP verification have no attempt-limiting control in the reviewed routes/services. Mail intake has a separate limiter; it does not protect login. Password verification calls synchronous Argon2 directly inside an async service. Invalid usernames deliberately incur the same expensive verification, which is good for avoiding a simple timing distinction but makes admission control particularly important.

**Evidence:** `server/src/radd/modules/auth/router.py:80`, `auth/service.py:336`, and `auth/security.py:23`. Eight sequential dummy-password checks took approximately 0.243 seconds on this host. That is an isolated CPU measurement, not a production load benchmark. Any separately deployed gateway protection was outside this review.

**Fix:** Add bounded account/IP attempt controls covering password, TOTP and directory login, with observable failures and a deliberate recovery policy. Offload hashing to a bounded execution path so it does not stall unrelated async requests. OWASP recommends login throttling as part of authentication defenses: [Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).

### 5. P2 — Comments do not participate in live cache invalidation

The realtime client maps a comment event to `Entity.comment` and `Entity.item`. The invalidation function only matches queries declaring those tags. `commentsQuery` declares neither, so an open thread does not refresh through this mechanism. Posting locally explicitly invalidates the comments key, masking the problem for the author while another user's thread stays stale.

**Evidence:** `web/src/lib/queries/items.ts:56`, `lib/cache.ts`, `lib/realtime.ts`, and `components/items/CommentsThread.tsx:133`. Executing the actual comment query options and invalidator with the installed QueryClient left `isInvalidated` false after a comment/item invalidation. Projects and states have similar missing-tag coverage worth auditing.

**Fix:** Complete the entity metadata contract, then enforce it for queries that represent live entities. Use the same invalidation path for mutations and realtime delivery. Add a two-client comment create/edit/delete check.

### 6. P2 — Several query keys identify different requests as the same data

| Query | Missing input in cache key | Consequence |
|---|---|---|
| `linkSearchQuery` | `excludeId` | Different parent/dependency pickers reuse results with the wrong excluded item. |
| `searchQuery` | `limit` | Small and large search surfaces can share incompatible result sizes. |
| `pageSearchQuery` | `limit` | Same issue for page searches. |
| `similarToTextQuery` | Text/revision and `excludeItemId` | An edited comment can reuse similarity results for its old text. |

**Evidence:** `web/src/lib/queries/activity.ts:66`, `ai-search.ts:63`, `ai-search.ts:89`, and `pages.ts:151`. Isolated execution of each factory confirmed equal keys for the differing inputs above.

**Fix:** Include all inputs that change the result. A content revision or stable text digest can identify long text without placing the whole body in a key. This matches the library's documented contract: [TanStack query keys](https://tanstack.com/query/latest/docs/framework/react/guides/query-keys).

### 7. P2 — Pagination is incomplete outside the main views

`childItemsQuery` supplies only `parent_id`; the API defaults to 50 rows. Both the issue's children section and board child expansion use it without a next-page mechanism. An epic with more than 50 direct children therefore has inaccessible children in these surfaces. `roadmapMembersQuery` fetches one page capped at 200, so a larger curated member set is also incomplete. The automation test panel's project item selector similarly uses a single 200-item request.

**Evidence:** `web/src/lib/queries/items.ts:79`, `server/src/radd/modules/items/router.py:75`, `web/src/components/items/ChildrenSection.tsx:55`, `components/board/CardChildren.tsx:32`, `lib/queries/views.ts:201`, and `components/automations/RuleTestPanel.tsx:52`.

**Fix:** Give every collection explicit pagination semantics. Show a total and load-more control for children, page or deliberately stream roadmap membership, and use server search for the automation test selector. Test 51 direct children and 201 roadmap members. The main view already has pagination; this finding is about the remaining secondary surfaces.

### 8. P2 — The shell is not usable at a normal phone width

The expanded sidebar has a fixed width of 240 px and starts expanded. At a 390 px viewport, Chromium measured the sidebar at 240 px and the main area at 150 px. The project action was clipped and the empty-state text wrapped into a narrow column. A user can manually collapse the rail, but the initial experience is still broken.

**Evidence:** `web/src/components/shell/Sidebar.tsx:182`, `shell/sidebar-prefs.ts`, and the screenshots below. The current issue body does have container-responsive layout; this is not a claim that the entire app contains no responsive rules.

**Fix:** Use an overlay navigation drawer below a breakpoint, preserve the full main width, and adapt page actions, tables, dialogs and the issue drawer to touch. Verify at 390, 768 and 1440 px, including zoom and a mobile keyboard. Prefer dynamic viewport sizing where appropriate over relying everywhere on `h-screen`.

| Current desktop shell, synthetic empty instance | Current shell at 390 px, same synthetic instance |
|---|---|
| ![Desktop shell](desktop.png) | ![Mobile shell](mobile.png) |

### 9. P2 — Too much JavaScript is required before choosing a feature

The build's main chunk is 1,422,358 bytes, approximately 374 KB using Vite's reported gzip estimate. Its entry plus explicitly preloaded JavaScript totals 1,806,135 bytes before compression, excluding CSS and further imports. The router eagerly imports the main routes, including administrative and importer screens, so even sign-in starts with a substantial application graph.

**Evidence:** `web/src/router.tsx:1`, `web/dist/index.html`, and the build output. Some expensive surfaces are already lazy-loaded; the opportunity is route-level separation, not redoing every existing dynamic import. These figures are build sizes, not measured production network transfer or an LCP score.

**Fix:** Split route components, particularly admin/import/reporting areas, and prefetch likely next routes. Establish an initial-load budget and inspect compression/cache headers on the actual deployment. Measure login → board → issue on a modest laptop and constrained network.

### 10. P2 — Realtime updates amplify unrelated work and have a slow-client bottleneck

Except for notifications, every event is sent to every authenticated connection. The browser then invalidates all active queries tagged with that entity, regardless of project or record. One busy project can provoke refetches in many unrelated tabs. Coalescing helps bursts but does not eliminate sustained amplification. Server sends are also awaited sequentially without an explicit per-send timeout, so a backpressured connection can delay later connections.

**Evidence:** `server/src/radd/modules/realtime/hub.py:25`, `realtime/broadcaster.py:31`, `web/src/lib/realtime.ts`, and `lib/cache.ts`. Frames carry entity/event types rather than issue bodies, so this is primarily a scaling and reliability finding, not evidence of issue-content disclosure.

**Fix:** Add permission-safe project/entity scoping and targeted invalidation, plus bounded per-client delivery with disconnect/resync behavior. Benchmark refetch counts and lag with multiple tabs and a slow client. Do not simply add more web replicas: the deployment docs explicitly identify single-replica operation as the current boundary.

### 11. P2 — Overlay accessibility has multiple implementations

The shared `Modal` now moves, traps and restores focus, which fixes an older audit finding. `IssuePanel` implements a separate overlay with `role="dialog"`, but does not provide equivalent initial focus, trapping or restoration. Each Modal also independently registers a document-level Tab handler, so nested dialogs and a peek above a modal require a topmost-overlay policy, not merely the existing Escape stack.

**Evidence:** `web/src/components/Modal.tsx:39`, `components/items/IssuePanel.tsx:23`, and `lib/dismiss-stack.ts`. This is source-verified; a full keyboard/screen-reader journey was not completed.

**Fix:** Share focus/overlay lifecycle between dialogs and drawers, make only the active modal trap focus, and test a similar-issue peek opened above an unfinished new-item form. The expected interaction is described by the [W3C modal-dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/).

### 12. P2 — Release validation is stronger than contribution validation

The release workflow gates image publication on backend tests and the host TypeScript/build checks. There is no app pull-request CI trigger. The five standalone JavaScript test files and browser proof scripts are not run by that test job, and `web/package.json` has no unified test/lint/check command. A clean build therefore misses the exact cross-account/cache and overlay behavior found above.

**Evidence:** `.forgejo/workflows/publish.yaml`, `.forgejo/workflows/ci-image.yaml`, `docs/contributing.md`, and `web/package.json`. The frontend script files themselves contain multiple assertions; “five” is the number of files reported by Node's test runner.

**Fix:** Provide one documented local verification command that CI also runs. Establish a safe PR validation path on the actual Forgejo setup, without exposing publishing secrets to fork code. Include the standalone tests and a small, deterministic browser suite for login/logout, board/issue, permissions, comments and mobile layout. Validate plugin remotes as well as the host.

## Design: what works and what needs refinement

The desktop visual language is coherent. Navigation and work areas are recognizable, typography is restrained, dark/light themes share tokens, and color mostly supports status rather than overwhelming the page. Key-addressed issues, a peek drawer, persistent view configuration and searchable selects suit frequent users. The shared issue/wiki editor and compact density option are worth retaining.

The supplied board and issue screenshots also reveal opportunities. The board cards devote considerable vertical space to a small amount of text, reducing scan density. The issue screen gives several secondary controls and empty sections substantial space, while the description and conversation compete with a long property rail. Search and My Work appear in more than one navigation area. The two top bands are useful once populated with pins, but can consume space without adding much for a new user. These are design judgments based on the supplied images and inspected components, not measurements of a live populated project.

My suggested design changes are:

- Make the default board card compact: key, title, assignee, priority and a small number of informative badges. Let teams opt into richer layouts; retain the existing card designer.
- Give description, current state, owner and conversation clear priority on the issue screen. Consider moving destructive and infrequent actions into an accessible overflow menu and offering progressive disclosure for empty sections.
- Explain “state”, “type”, “kind”, “cycle”, “release”, “view” and “queue” through context and templates. The underlying flexibility is valuable; presenting the whole vocabulary immediately raises the learning cost.
- Make advanced SLQ discoverable while providing obvious structured filters and a clear distinction between search and optional AI Ask.
- Improve the first-run path: choose a project purpose, create/import a project, invite colleagues, file the first issue. The existing empty states provide individual actions but do not guide that journey.
- Treat keyboard, touch and screen-reader behavior as part of the design system. Icon affordances and hover-revealed actions should remain understandable without a mouse.

I checked the light-theme sign-in warning rather than assuming raw amber classes meant poor contrast. The browser resolved its foreground to `[180,83,9]`, showing that the existing palette remapping is active. I am **not** reporting that warning as an unreadable-color bug. There are still 325 raw red/amber/green/blue/indigo/zinc utility occurrences in the main frontend scan; gradually migrate semantic statuses to the existing semantic tokens to reduce maintenance of both mechanisms. This count is a maintenance signal, not 325 accessibility failures.

## Redundant and old code: remove deliberately

| Candidate | Recommendation and evidence |
|---|---|
| Wave-1 anonymous development authentication | Remove from normal builds or put behind an explicit development flag. `web/src/lib/auth.ts:8` interprets `/auth/me` 404 as anonymous dev mode, and `lib/hooks.ts:194` grants all UI capabilities in that mode. Auth is now a core part of the app. A misrouted endpoint should produce an understandable service error, not an apparently unrestricted shell. This does not by itself bypass backend authorization. |
| “Auth/comments not deployed yet” UI branches | Retire the historical rollout explanation. `routes/login.tsx` and `components/items/CommentsThread.tsx:163` should distinguish unavailable service, missing record and permission failure using the current contract. Keep optional-module handling where optionality is real. |
| Stale frontend user-source vocabulary | `web/src/lib/types/users.ts:90` and `UserSourceBadge.tsx` retain `unknown`, while the backend enum documents that those rows were migrated away. Align the human-user and service-account wire types with the actual schemas. |
| Incomplete service export bookkeeping | `items/service/__init__.py` imports clone/convert/merge but omits them from `__all__`. These functions are used, so fix the public export declaration rather than deleting them to silence lint. |
| Unused imports and assignments | Ruff reported 84 diagnostics across source and tests: 37 F401 and 23 F841 among them. Some imports register bindings; many “unused” assigned calls enforce permissions or existence. Remove the unused binding while preserving required calls. Do not run a blind deletion sweep. |
| Overlapping cache conventions | Central entity invalidation coexists with handwritten per-key invalidation and incomplete metadata. Consolidate behavior; otherwise each new query creates another opportunity for missed refreshes. |
| Custom transaction-buffer middleware | Evaluate replacement, not immediate deletion. The commit-before-response invariant is important and the old download-buffering defect has been fixed. Current FastAPI supports function-scoped dependency teardown before sending the response, potentially simplifying `middleware.py` and `db.py`. Audit nested dependencies and streaming consumers first. [FastAPI dependency scopes](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope). |
| Historical narrative in working documentation | Keep the history, but move release narratives out of the primary contributor/agent agreement. `CLAUDE.md`, `PLAN.md` and `BUILD-LOG.md` are large and partially overlap. A concise current architecture and workflow document would lower contributor onboarding cost. |

Do **not** indiscriminately remove migrations, registered hooks, API-only extension endpoints, or public service re-exports because a text search finds no ordinary caller. The `/kb` redirects explicitly preserve public links until v1, and encrypted-secret plaintext adoption exists to upgrade stored data; each needs an actual migration/support policy before deletion. A conservative repository-wide identifier scan did not identify an obvious unreferenced exported frontend symbol, which is not proof that every export is reachable.

The July/August audit reports should remain historical. I verified that the current tree contains module-boundary enforcement with an empty exception allowlist, a running task-backend mechanism, searchable selects, shared-modal focus trapping, corrected linked-page paths, file/SSE middleware bypasses, and a set-based rank rebalance. Re-reporting their former defects would send effort in the wrong direction.

## Maintainability and performance beyond the immediate fixes

The largest risk is the concentration of behavior, not the raw file count. `routes/view.tsx` is 1,322 lines; `TransitionsSection.tsx` is 1,029; `RichEditor.tsx` is 924; the automation executor is 1,112; views service is 959; mail intake is 898. There are 81 frontend and 92 backend source files above 300 lines. Split by responsibility and testable policy boundaries: view query state versus presentation, authorization versus merge application, automation planning versus execution, and editor lifecycle versus feature registration. Arbitrarily slicing files at a line limit would not solve this.

The five architecture-contract functions passed when invoked without database fixtures. That supports preserving the modular monolith. One limitation of the import checks is that raw SQL table names can still couple modules, as the merge repoint table demonstrates. Merge's foreign-key coverage test is a useful compensating check; polymorphic references and authorization need their own contracts.

Additional performance work should be driven by representative datasets:

- Comments currently load all rows for a parent and render the whole thread. Page long discussions after visibility filtering, preserving stable ordering and scroll position.
- Sidebar projects/views/cycles and several directory-style queries still fetch complete collections before filtering. Searchable UI alone does not bound database work or payload size.
- Rank rebalance is now one SQL statement, but still rewrites the global rank order inside the interactive reorder path. Measure its lock duration and WAL cost at scale; the previous per-row round-trip problem is fixed, the global write remains.
- Pass TanStack's cancellation signal through `api.ts`; obsolete typeahead requests currently keep running.
- Keep the documented one-app-replica boundary explicit. Reconcile plugin state and background work before promising horizontal scaling or highly available operation.

Useful benchmark scenarios are a small working team, a 50k-issue project, a 500k-issue import, an epic with 51+ children, a long mail-driven discussion, and many simultaneously open tabs. Record endpoint p50/p95, database query counts, event backlog, browser long tasks, initial JS and request counts. This audit did not produce those load-test results.

## What would make this a stronger free open-source tracker

The differentiation is already credible: access controls, SSO, custom fields, automation, service desk and APIs in the application, with optional AI and a self-hosted deployment. The highest-return product work is making those capabilities easy to trust and adopt.

1. **Reliability release:** credential scope, merge authorization, account cache isolation, live comments, and pagination. These should precede promotional growth.
2. **Usability release:** responsive shell, keyboard-safe overlays, compact default cards, clearer action hierarchy, and a guided first project. Measure success as time to file, find and resolve an issue.
3. **Low-friction adoption:** a documented pinned prebuilt-image quick start alongside source builds, a safe first-admin setup flow, tested upgrade paths, and a small demo/reset procedure. Fix the contributor setup sequence: it enters `server` and later says `cd web`, which needs `cd ../web` in that shell.
4. **Account administration:** local password recovery, active-session listing/revocation and useful authentication audit events. I did not find a dedicated recovery/session-management UI in the reviewed auth routes/profile page. Integrate these with existing SSO/MFA rather than inventing another identity system.
5. **Conversation quality:** threaded replies, reactions and notification controls suited to a busy project. Inline anchored/resolvable comments already exist; ordinary reply relationships and reactions are not present in the comment model inspected here.
6. **Integration focus:** prioritize GitHub and Slack if the intended audience is open-source development teams; the existing integrations concentrate on Forgejo/Gitea, GitLab and Google Chat. Validate demand before adding another maintenance-heavy connector.
7. **Internationalization:** externalize user-facing strings and plan RTL layout. The app has an Arabic name, but the current UI is English with hardcoded strings and `<html lang="en">`. Translation is a meaningful route to community contribution.
8. **Contributor confidence:** PR checks, a concise architecture map, a single check command, issue templates and documented plugin compatibility. Explain public API stability and generate or validate frontend wire types against OpenAPI to catch vocabulary drift.
9. **Data portability:** complement the detailed Jira/Confluence import story with a documented, complete, reusable export story and round-trip examples. Existing CSV and backup capabilities solve parts of this; machine portability needs clear coverage of comments, attachments, relationships, custom fields and identities.

These are product priorities inferred from the current implementation, not a competitor feature checklist. I would preserve the single-container-plus-Postgres operational model and optional AI while closing the above gaps.

## Validation record

| Check | Result |
|---|---|
| `cd web && npm run build` | Passed. Large-chunk warnings and CSS optimizer warnings about `::highlight` were emitted; the warning is not itself proof that the browser feature is broken. |
| `node --test web/scripts/*.test.mjs` from repository root | Five test files passed. |
| `pytest --collect-only -q` in server venv | 2,349 tests collected; this is discovery, not execution. |
| Architecture contracts invoked directly | All five passed; no database fixtures used. |
| Ruff source + tests | 84 diagnostics, retained in `ruff.txt`; no automatic fixes applied. |
| Isolated credential-scope checks | Confirmed unscoped minting and admin guards ignoring empty key scope. |
| Isolated merge check | Confirmed the service proceeds without enforcing the actor's relationship to the source. |
| Query factories + installed QueryClient | Confirmed four cache-key collisions and missing comment invalidation. |
| Chromium current build with synthetic API | Desktop/mobile shell rendered without captured console errors; 390 px layout defect and retained cache entry confirmed. The API and live WebSocket behavior were simulated/unavailable. |
| Full backend/integration/load suite | Not run: no Postgres available and local Podman storage failed. |

Evidence files and isolated reproduction scripts accompany this report. They are audit tools, not additions to the app's regression suite. No production service was probed or changed.

Run the isolated checks from the repository root using the existing dependencies:

```bash
server/.venv/bin/python research/audit-2026-09-09/token-scope-proof.py
server/.venv/bin/python research/audit-2026-09-09/merge-authorization-proof.py
node research/audit-2026-09-09/cache-proof.mjs
```

The optional `browser-proof.mjs` requires the built `web/dist`, Chromium and free localhost ports 18765/18766. It serves synthetic data, uses a temporary browser profile, and writes screenshots/results to `/tmp` and stdout. The Python checks mock database writes; they do not connect to Postgres.
