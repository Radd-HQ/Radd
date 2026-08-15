# Radd gap analysis — critical missing features vs modern issue trackers

Audit date: 2026-08-05. Read-only audit of `` (server `src/radd/modules/`, `web/src/`, CLAUDE.md, docs/modules.md). Every claimed gap was verified by grep/read of the named files; several presumed gaps turned out to exist and are listed in the inventory instead.

## Executive summary

1. **No mobile/responsive layout** — the app shell has zero responsive breakpoints; unusable on a phone. (CRITICAL)
2. **Long lists lack search/filter inputs** — user-confirmed; only 2 of ~20 settings surfaces have a filter box. (CRITICAL)
3. **No Slack/Teams/Discord notification connectors** — Google Chat + generic webhooks only; Slack is where most teams live. (CRITICAL)
4. **No comment threads or reactions** — comments are flat; no replies, no emoji reactions. (IMPORTANT)
5. **No first-class recurring tasks** — composable via scheduled automations, but no per-item recurrence UX. (IMPORTANT)
6. **No guest/external collaborator access** — email loop and public forms exist, but no read-only guest accounts. (IMPORTANT)
7. **AI is not wired into automations** — no auto-label/auto-assign/auto-priority triage actions despite "AI-native" positioning. (IMPORTANT)
8. **Keyboard-first navigation is shallow** — palette + one "c" hotkey; no j/k, no single-key assign/status/priority. (IMPORTANT)
9. **Security surface gaps** — no session list/revoke UI, no login events in the audit trail, no API rate limiting. (IMPORTANT)
10. **Duplicate detection at creation only covers resolved issues** — open duplicates are not surfaced while filing. (IMPORTANT)
11. **No item edit-conflict guard** — pages have optimistic 409s; item descriptions are last-write-wins. (IMPORTANT)
12. **No capacity/workload planning** — no per-person load view, no cycle capacity. (IMPORTANT)

## What exists (inventory)

Radd is far more complete than its module count suggests. Items carry first-class **priority, start/target dates, overdue badges** (`items/models.py:49,70-71`; `web/src/components/items/ItemBadges.tsx`), story points, rank, flags, per-user **stars**, archive, and **cross-project move with key aliases** (spec 68, `ItemKeyAlias`). It has **issue templates per type** (spec 76, `itemtypes/models.py: description_template`), **epic progress rollups** (`items/rollup.py`, `RollupBar.tsx`), **bulk edit + bulk move** (`items/bulk.py`, `BulkActionBar.tsx`), dependency links with user-definable link types, a **roadmap/Gantt view with dependency connectors and bar drag** (`web/src/components/roadmap/Connectors.tsx`, `useBarDrag.ts`), **board WIP limits** (`WipLimitMenu.tsx`) and per-column point sums, **burndown/velocity reporting** (`reporting/timeline.py`, global reports), **cycle carryover on completion** (`cycles/history.py`), **scheduled + manual + any-event automations** with conditions and a rich action set (`automations/types.py`), **workflow guards + multi-approver approvals** (`approvals/models.py`), a two-dialect **SLQ query language** with autocomplete and NL→SLQ, hybrid FTS+pgvector search, a ⌘K palette with semantic Ask mode, **watchers/inbox/mentions** (user @ and issue #), **KB deflection while typing a new issue** (`NewItemModal.tsx:190`), email intake whose **replies land as comments and thread outbound** (`mailintake/poller.py:161`, `outbound.py`), per-view **CSV export** (`web/src/lib/csv.ts`), **recently-viewed items** (`web/src/lib/recent.ts`, surfaced on My Work), a wiki with **version history, optimistic-concurrency 409s, inline anchored+resolvable comments, per-page permissions, and page templates** (`pages/models.py`, `comments/models.py`, `pages/page_access.py`, `pages/templates.py`), backups **with a restore path** (`backup/router.py`), an audit viewer, admin impersonation ("View as", RADD-836), service accounts with scoped keys, a 19-tool MCP surface, SSO (OIDC/Google/LDAP) with MFA, and a full plugin platform.

## 1. Issue/work management

- **Recurring tasks — IMPORTANT.** No per-item recurrence (`grep -riE "recurr"` hits only cycles and page templates). Scheduled automations (spec 69, `automations/models.py:31-33`) + `CREATE_ITEM` can fake it, but there is no "repeat this task weekly" affordance on an item, no recurrence metadata, no link between instances. Jira, Asana, Height, and Todoist-class tools have first-class repeat. Fit: an `items` addendum or small `recurrence` plugin storing a rule per item and reusing the automations scheduler.
- **Duplicate detection at creation (open items) — IMPORTANT.** The DeflectionPanel surfaces KB pages and **previously RESOLVED issues** only (its own docstring, `DeflectionPanel.tsx:16-18`). Filing "board scroll broken" while an open BOARD-SCROLL bug exists shows nothing. Linear and GitHub surface open similar issues while typing. Fit: the `POST /ai/similar` fusion seam already exists — point it at the new-item title with open-state filtering, no new module.
- **Item merge — IMPORTANT.** No merge that moves comments/watchers/worklogs onto a survivor (`grep merge` in `items/service/` — only custom-field dict merges; spec 89's merge is users). A `duplicates` link type exists, but service-desk-style merge (Zendesk, Jira "close as duplicate" plus manual copy) is stronger. Fit: `items/service/merge.py` reusing the polymorphic comment repoint and the notify watcher tables.
- **Personal drafts — NICE-TO-HAVE.** No draft issues (`grep -riE "\bdraft"` hits only SLQ draft validation, `items/router.py:95`). Linear keeps unfinished issue drafts. Fit: localStorage in `NewItemModal` would cover 90%.
- **Blocked-by cascade indicators — NICE-TO-HAVE.** Dependencies render on the issue page (`DependenciesSection.tsx`) and as roadmap connectors, but board/list cards show no "blocked" badge (`ItemBadges.tsx`, `card-cells.tsx` — no blocked hit) and nothing shows transitive impact. Linear shows a blocked icon on cards. Fit: a `blocked` computed chip in the card-cell registry (`components/board/card-cells.tsx`).
- **Archival/retention policies — NICE-TO-HAVE.** Soft archive exists (`archived_at`); no auto-archive of old done items, and no event-outbox pruning anywhere (`grep -riE "retention|prune|purge"` over events/audit: nothing). Fit: a scheduled maintenance job in `events`/`items`.
- Verified present, not gaps: priority, due (target) dates + overdue surfacing, start dates, bulk edit, move between projects, sub-issue rollups, issue templates per type.

## 2. Planning

- **Capacity/workload planning — IMPORTANT.** Zero hits for "capacity" anywhere in server or web. No per-person load view, no cycle capacity vs points, despite leave data (`leave` module) that would make it uniquely good. Jira/Asana/Height all ship workload views. Fit: a `capacity` plugin joining cycles × estimates × `leave/calendar` — the data is all already public service functions.
- **OKR/goal linkage — NICE-TO-HAVE.** No hits for "okr|objective". Linear (Initiatives), Asana (Goals), Plane (Cycles+Modules) have goal layers. Fit: an EntitySpec plugin like `milestones` with an item-link relation.
- **Milestones are shallow — NICE-TO-HAVE.** The module is the plugin-platform north star: a kernel-generated entity with title/description/due_on/status and a CRUD page (`milestones/spec.py:20-24`) — not rendered on roadmaps, not linkable to items, no progress. GitHub milestones group issues and show progress. Fit: extend the plugin with an item relation + a roadmap marker slot.
- **Estimation beyond points — NICE-TO-HAVE.** Points (`estimate_points`) and time estimates (timelogging) exist; no t-shirt scale option. Fit: a project setting mapping labels onto the points column.
- Verified present, not gaps: velocity charts (global reports, spec 19), burndown (`reporting/timeline.py`), cycle carryover on completion (`cycles/history.py`), Gantt-grade roadmap (connectors, drag, milestones excepted).

## 3. Collaboration

- **Comment threads/replies — IMPORTANT.** `comments/models.py` has no parent-comment column: flat stream (plus inline anchored comments on text, RADD-726 — genuinely ahead of Jira there). Linear, GitHub, Asana, Height all thread. Fit: a nullable `reply_to_id` on `Comment` + a collapsed-thread render in `CommentsThread.tsx`.
- **Comment reactions — IMPORTANT.** No reactions model anywhere (`grep -riE "reaction"` hits only SLA/hooks false positives). Reactions kill "+1" noise; every competitor has them. Fit: a tiny `comment_reactions` table in `comments`, rendered in `CommentsThread.tsx`.
- **Guest/external access — IMPORTANT.** No guest concept (`grep -riE "guest"`: nothing). Mitigations exist — public tokened forms, public CSAT, public KB, mail contacts with outbound replies, `participants` as internal second reporters — but a client who should *see* their ticket in-app cannot without a full account/role. Jira Service Management, Linear (guests), Asana guests all cover this. Fit: a `guest` UserSource with a participant-scoped permission floor — spec 113's source machinery is most of it.
- **Team @-mentions — NICE-TO-HAVE.** Mentions are `@[Name](uuid)` users and `#` issues (`notify/planner.py` has no team path; `items/mentions.py`). Fit: a team token in the mention picker fanning out through the existing planner.
- **Real-time co-editing — NICE-TO-HAVE.** No CRDT/yjs anywhere. Pages at least 409 on stale versions (`pages/models.py:40-42`); acceptable for now, see §9 for the item-side gap.
- **Public roadmap/changelog — NICE-TO-HAVE.** Public pages exist (spec 74) but releases have no public face (`grep -ni public` in `releases/`: nothing). Linear/Productboard-style public roadmaps drive community projects. Fit: a public tokened releases page in the `releases` module, same idiom as `/kb`.
- Verified present, not gaps: approval flows (deep: per-transition rules, snapshot, votes — `approvals/models.py`), email reply → threaded comment (`mailintake/poller.py:161`), edit-conflict handling on wiki pages.

## 4. Views & navigation

- **Keyboard-first depth — IMPORTANT.** The palette (⌘K, Ask mode) and one board hotkey ("c", `constants/ui.ts:56`, used only in `view.tsx`) plus the editor `/` quick-action menu (`items/quick-actions.ts`) is the whole story. No j/k list traversal, no focused-issue single-key assign ("a"), status ("s"), priority ("p"), label ("l"), no "go to" chords. Linear's adoption case is substantially this. Fit: a shell-level shortcut registry (kernel-ish, plugins contribute) + roving focus in `ViewList`/`ViewBoard`.
- **Saved-query subscriptions — IMPORTANT.** No way to be notified when a view/SLQ result set changes (`grep -riE "subscri"` in views/notify finds only a project-seed hook, `views/__init__.py:5`). Jira filter subscriptions and Zendesk view alerts are staples for leads. Fit: a `views` addendum — a scheduled evaluator diffing result sets into the notify pipeline (the automations scheduler pattern already exists).
- **Group aggregates in lists — NICE-TO-HAVE.** Board columns show Σ points (`ViewBoard.tsx:36-38`); list group headers show only a done-count pill (`ViewList.tsx` — no points/sum). Height/Airtable-style per-group sums are expected. Fit: extend the group header in `ViewList.tsx` with the board's `formatPoints` logic.
- Verified present, not gaps: recent items (spec 37, `lib/recent.ts`, My Work), favorites (item stars + view/link pins), WIP limits, per-view CSV.

## 5. Search & AI

- **AI triage in automations — IMPORTANT.** `ActionType` (`automations/types.py:66-87`) has set_state/priority/assignee/labels/webhook/chat/email — and no AI action. An "AI-native" tracker should let intake auto-label, auto-route, auto-prioritize via the `ai/client.py` seam (`complete_choice` is literally built for enum-constrained answers like "which team"). Competitors are shipping this now (Jira Intelligence, Linear triage suggestions). Fit: an `ai_classify` ActionType in `automations` calling `complete_choice`, feature-gated like every other AI seam.
- **AI duplicate detection on create — IMPORTANT.** Covered in §1 — the machinery (similar fusion, embeddings) exists; the surface doesn't.
- **Meeting notes → issues — NICE-TO-HAVE.** No extraction flow ("meeting" hits only timelogging categories). Fit: an editor AI action ("extract action items") emitting draft items — the reviewable-diff pattern already exists.
- **Palette operators — NICE-TO-HAVE.** The palette is keyword + semantic Ask + goto/actions (`CommandPalette.tsx`); no inline filters (`assignee:me`) — mitigated by the SLQ query bar on views, so low priority.
- Verified present, not gaps: NL→SLQ with value repair on items *and* worklog dialects, semantic search, summarize digests, editor AI with diff review, MCP `find_items`.

## 6. Long lists lack search/filter inputs (CONFIRMED — user observation)

Confirmed as a systemic category. Of the settings surfaces, only **Cycles** (`settings/cycles.tsx:105`) and the **field-options sub-list** (`settings/fields.tsx:312`) render a filter input; **Users, Groups, Teams, Labels, Link types, Pages spaces, Roles, Canned responses** have none (grep for `placeholder=.*(search|filter)` across `web/src/routes/settings/`). The worst offender noticed in passing is **Settings → Users** on a directory-fed instance — CLAUDE.md records a live AD with 1031 active accounts, unfilterable. Given the dev DB seeds 503k items, any unfiltered list is a real wall, not a cosmetic one. See the dedicated surface-by-surface audit in `08-list-search-filters.md`; the systemic fix is a shared filterable-list primitive rather than per-page inputs. **CRITICAL.**

## 7. Ops/enterprise

- **Session management UI — IMPORTANT.** `sessions` table exists (`auth/models.py:70`) but there is no `GET /auth/sessions` or revoke endpoint (`auth/router.py` — only deactivation-revokes) and Profile shows nothing. "Where am I logged in / sign out everywhere" is table stakes for a security review. Fit: two `auth` endpoints + a Profile section.
- **Login/auth audit events — IMPORTANT.** `AuthEvent` (`auth/types.py:786-798`) has user/role CRUD and impersonation — **no login succeeded/failed, no session created, no token used**. The audit page (`settings/audit.tsx` over `audit/service.py`, a filtered viewer on the events outbox, admin-only) therefore cannot answer "who signed in when", and there's no audit export. Fit: emit `auth.login_*` events from `create_session` (one seam covers all four login paths, as spec 113 proved).
- **API rate limiting — IMPORTANT.** No rate-limit anywhere (`grep -riE "rate.?limit"`: nothing). Public endpoints (login, tokened forms, CSAT, KB) are brute-forceable. Fit: a kernel middleware with per-route budgets in `config.py`.
- **Full data export — IMPORTANT.** CSV export is client-side and capped at the loaded page (`lib/csv.ts:28` "inherits the page cap"); the only full export is an admin `pg_dump` backup. No per-project JSON/CSV export a team lead can run — the exit-path question every self-hosted evaluation asks. Fit: a streaming `GET /projects/{id}/export` in a small `export` module walking public service functions.
- **SCIM provisioning — NICE-TO-HAVE.** Absent (no hits); LDAP sync + OIDC group→role covers most of the need for the target audience.
- **IP allowlisting — NICE-TO-HAVE.** Absent (hits are SSO domain allowlists); reverse-proxy territory for self-hosted.
- Verified present, not gaps: backup **with restore** (upload → `pg_restore`, watchable run, schedules — `backup/router.py`), audit UI (thin but real), monitoring page, impersonation audit.

## 8. Mobile & notifications

- **Responsive layout — CRITICAL.** `web/index.html` has the viewport meta, but only 18 of ~300 TSX files use any `sm:/md:/lg:` prefix, and **the shell has zero** (`routes/app-layout.tsx`, `components/shell/TopBar.tsx` — no `md:` at all). The Cairn-band shell (top bar + pins bar + sidebar) has no narrow mode; on a phone, checking an issue from an SLA-breach email is effectively impossible. Every competitor has at least a responsive web app. Fit: a shell-first responsive pass (collapsible rail already exists) before any native-app talk.
- **Slack/Teams/Discord — CRITICAL (as a set; Slack specifically).** Only `googlechat` exists; `POST_CHAT` posts to a bare webhook URL (`automations/engine.py:276-280`) with no Slack Block Kit/Teams card formatting, no channel routing, no interactive unfurls. Zero hits for slack/discord/teams as connectors. For most prospects, "does it ping Slack" is question one. Fit: sibling connector plugins to `googlechat` — the connector shape is proven three times over.
- **Notification digest options — NICE-TO-HAVE.** The "digest" is a 5-minute batching loop (`notify/emailer.py`, `config.py: notify_email_interval=300`), with a single on/off per user. No daily/weekly summary, no quiet hours. Fit: a cadence field on `NotificationPref` consumed by the same emailer.
- **Per-event preference granularity — NICE-TO-HAVE.** `NotificationPref.muted_types` is global per type (`notify/models.py:59`); no per-project overrides. Linear/Jira allow per-project tuning. Fit: a `project_id` column on the pref table.
- **Calendar sync — NICE-TO-HAVE.** No ICS anywhere. Due dates and cycle boundaries as a tokened ICS feed is cheap and loved. Fit: a `GET /calendar.ics` tokened endpoint in `items` or a `calendar` plugin.

## 9. Wiki/docs depth

The wiki is stronger than expected: page templates with placeholders (`pages/templates.py`, RADD-712), version history + optimistic concurrency (`pages/models.py`), **inline anchored + resolvable comments** (`comments/models.py`, RADD-726 — ahead of Confluence's model), per-page permissions on the access framework (`pages/page_access.py`), public KB, print/PDF with subpages (`page-print`), FTS + semantic search, issue links.

- **Item-description conflict guard — IMPORTANT (and it's an items gap, found here by contrast).** Pages 409 on stale `expected_version`; item PATCH has no version field at all (`grep expected_version` in `items/schemas.py`: nothing) — two people editing a description is silent last-write-wins, with realtime WS making the race *likelier* (you see the other person's save only after yours clobbered it). Fit: copy the pages idiom onto `WorkItem.description` updates.
- **Real-time co-editing / presence — NICE-TO-HAVE.** No CRDT; not even "someone else is editing" presence, though the realtime WS layer could carry it cheaply. Fit: a presence broadcast over the existing `realtime` socket first; CRDT only if dogfooding demands it.
- **Structured export — NICE-TO-HAVE.** Print/PDF exists; no markdown/space bulk export (exit-path story, same theme as §7). Fit: a zip-of-markdown endpoint in `pages`.

## Top 10 by adoption impact

1. **Responsive/mobile shell** — evaluators open it on a phone in the first hour; zero breakpoints in the shell is a first-impression killer.
2. **Slack notification connector** (then Teams/Discord) — the most common "does it integrate with…" question; a proven connector pattern makes this cheap.
3. **Search/filter inputs on every long list** (confirmed) — one shared component; the Users page at 1031 AD accounts is the poster child.
4. **Comment threads + reactions** — the most visible daily-use collaboration gap; flat comments read as dated immediately.
5. **AI triage automation actions** — the positioning is "AI-native"; automations that can't call the AI undercut the pitch, and the `complete_choice` seam makes it a small change.
6. **First-class recurring tasks** — asked for by every ops/IT team in week one; the scheduler already exists.
7. **Guest/external access** — unlocks agencies, client work, and service-desk requesters seeing their own tickets.
8. **Keyboard depth (j/k, single-key actions)** — the Linear-refugee audience specifically shops for this.
9. **Security surface bundle: session UI + login audit events + rate limiting** — three small changes that together pass or fail a security review.
10. **Open-duplicate detection at creation + item merge** — closes the loop the deflection panel started; keeps a public demo tracker from accumulating dupes.
