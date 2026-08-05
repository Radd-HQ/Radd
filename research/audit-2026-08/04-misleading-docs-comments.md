# Documentation audit — Radd (`<repo>`), 2026-08-05

## Executive summary

Read-only audit of docstrings, comments, doc files, and API descriptions against the code. **~50 verified contradictions** (5 high, ~18 medium, rest low), plus an auditable sample of ~60 strong claims that checked out. One systemic cause dominates: **spec-wave staleness** — documentation written before specs 50/86/91/92/102/111/115 and RADD-740/788/791/816/829 was never updated when the mechanism moved. The five worst findings:

1. **CLAUDE.md's entire status preamble is a 0.9.0-era snapshot**: newest git tag is **v0.21.0** (twelve releases undocumented), no `kernel-plugin-platform` branch exists, "Tests 1335" is now 1570, and the cited `/health` endpoint does not exist.
2. **`merge_users`' docstring promises a deactivated audit shell; the code hard-deletes the source account** (`auth/service.py`) — a data-retention lie, echoed in `delete_user`'s docstring.
3. **docs/modules.md line 156 lists pgvector semantic search as an unbuilt gap** — it shipped in spec 103 (`GET /search/semantic` exists).
4. **`PUT /views/{id}/sharing`'s OpenAPI description documents per-user/team grants the endpoint can no longer set** (spec 92 moved them to `/grants`).
5. **Service accounts' "never mistaken for a person / never notified" comment is false on all three counts** — the directory endpoint hides the distinguishing email/source, they are assignable and get notification rows, and the synthetic domain is only a default.

Positives worth noting: the tree contains **zero genuine TODO/FIXME/XXX/HACK markers**; the "zero raw `zinc-*`/`indigo-*` utilities in web/src" claim **holds**; and docs/plugin-ui.md and docs/deploy.md are almost entirely accurate on concrete citations. Caveat on age-dating: public git history was squashed to an initial commit on 2026-08-02, so pre-squash comment ages are unrecoverable via blame.

---

## (a) docs/modules.md drift

Audited `docs/modules.md` (291 lines) against `server/src/radd/modules/`. **53 actual modules; 50 have table rows; none documented-but-deleted.** The doc's "Depends on" cells mirror each plugin's `depends_on` declaration — the systemic drift is that **neither the cells nor the code's `depends_on` track real module-scope imports**.

| Module | Table row? | Accurate? |
|---|---|---|
| access, ai, alertmanager, approvals, attachments, audit, auth, automations, backup, canned, comments, csat, cycles, dashboards, events, fields, forgejo, forms, gitlab, googlechat, groups, items, itemtypes, jiraimport, labels, ldap, leave, linktypes, mailintake, mcp, monitoring, notify, pages, participants, projects, realtime, releases, reporting, screens, search, settings, slas, sso, teams, timelogging, vcs, views, webhooks, weblinks, workflow | yes (50 rows) | mostly; specific cell drift below |
| **capabilities** | **no row** | prose only (line 36) |
| **pluginmgr** | **no row** | prose only (line 30); its 4 events documented nowhere |
| **milestones** | **no row** | prose only (line 32) |

**Findings** (line numbers are in `docs/modules.md` unless noted):

- **HIGH** — `docs/modules.md:156` — says pgvector semantic search is a "remaining cross-cutting gap". It shipped (spec 103): `server/src/radd/modules/search/router.py:80` (`GET /search/semantic`), `ai/embeddings/` exists. Same line uses eradicated "per-workspace" vocabulary. *Fix: rewrite the gaps line.*
- **HIGH** — `docs/modules.md:95` — `ai` row depends on "workspace, auth, items" — `workspace` no longer exists (renamed `projects`, spec 86, per the doc's own line 59). Actual: `ai/__init__.py:84` declares seven modules. *Fix: replace cell with the real tuple.*
- **HIGH** — `docs/modules.md:79` — `views` row describes the `view_shares` table in present tense. It was migrated + dropped by spec 92 (migration `925809931622_spec_92_migrate_view_shares_to_access_.py`; `views/models.py` has no such table); contradicts the doc's own access row (line 70). *Fix: describe sharing as access grants.*
- **MEDIUM** — `docs/modules.md:202-210` — "Field grant semantics" describes the dropped `field_permissions` table as current; the code resolves via spec-92 `access_grants` (`fields/service.py:294,320`). *Fix: rewrite in access-grant terms.*
- **MEDIUM** — `docs/modules.md:65` — workflow emits documented as `transition.created/.updated/.deleted`; actual strings are `workflow_transition.*` (`workflow/types.py:182-185`, emitted `workflow/transitions.py:303`). A subscriber following the doc subscribes to an event that never fires. *Fix: correct the three names.*
- **MEDIUM** — `docs/modules.md:74` — `item.deleted` (registered `items/__init__.py:42`, emitted `items/service/core.py:326`) appears nowhere in the doc. *Fix: add to emits cell.*
- **MEDIUM** — pluginmgr's `plugin.installed/enabled/disabled/uninstalled` (emitted `pluginmgr/service.py:154` + siblings) are documented nowhere. *Fix: add pluginmgr/capabilities/milestones rows.*
- **MEDIUM** — `auth.view_as_started`/`auth.view_as_ended` (emitted `auth/service.py:311,328`) undocumented. *Fix: add to auth row.*
- **MEDIUM** — `docs/modules.md:87` — attachments depends cell predates spec 102: module-scope imports of `access` (`attachments/acl.py:18-21`) and `ai` (`attachments/routing/engine.py:77-78`), plus teams/groups, are missing. *Fix: extend cell.*
- **MEDIUM** — `docs/modules.md:74` — items depends cell omits `itemtypes` (module-scope import in 8 files, e.g. `items/schemas.py:10`), `linktypes`, `approvals`, `access`; `itemtypes`/`linktypes` are also missing from `items/__init__.py:31-33` `depends_on`. *Fix: extend cell and code tuple.*
- **MEDIUM** — `docs/modules.md:94` — mcp depends cell predates the 0.4.0 tool wave: `releases` (`mcp/tools.py:29-31`), `timelogging` (`tools.py:32-34`), `search` (`tools.py:168`) etc. missing (also from `mcp/__init__.py:11`). *Fix: extend both.*
- **MEDIUM** — `docs/modules.md:7` — "all 49 builtin plugins"; `config.py:323-374` lists 52 (plus installable milestones). *Fix: "all 52".*
- **LOW** — `docs/modules.md:30` — names the optional plugin `docs`; it is `pages` (`pages/__init__.py:22`, `config.py:361`).
- **LOW** — depends-cell omissions verified at module scope or deferred import: releases (line 73: pipeline imports items/settings/workflow/automations — `releases/pipeline.py:20-26`), forgejo (line 96: `forgejo/router.py:17` imports `releases.pipeline`; absent from `depends_on` too), views (line 79: code declares `access` not documented; `groups` imported `views/service.py:22`), timelogging (line 82: settings — `timelogging/timesheet_router.py:14-15`), automations (line 83: fields/notify/mailintake — `automations/engine.py:36-43`, `email_action.py:29`), notify (line 84: participants — `notify/consumer.py:150`), access (line 70: groups — `access/service.py:111`).
- **LOW** (code noise, not doc drift): `forgejo_connection.*`/`forgejo_repo.*` (`forgejo/types.py:52-58`) and `field_rule.updated` (`fields/types.py:49`) are enum values never emitted.

Verified clean for balance: the `leave` row matches code exactly; all 12 spot-checked documented event families resolve to live, emitted enum values; `workspace.created` appears only in historical narrative.

---

## (b) Wrong docstrings (incl. FastAPI endpoint descriptions)

### Python docstrings

- **HIGH** — `server/src/radd/modules/auth/service.py:693-695` — `merge_users` docstring: "the source's credentials are revoked and the account deactivated (kept for audit)." The code **deletes the row** (`await session.delete(source)`, line 756; the inline comment at 730-732 says "The source is DELETED, not deactivated"). The false claim is echoed at `auth/service.py:955-957` (`delete_user`: "unlike `merge_users`, which keeps a deactivated shell for audit"). *Fix: both docstrings should say the source is deleted after repointing, with the `user.deleted` event payload (lines 742-755) as the surviving audit record.*
- **MEDIUM** — `server/src/radd/modules/automations/engine.py:429-434` — `apply_event`: "a matching rule on an itemless event logs and skips its actions (they are all item-bound today)." False since spec 58b: universal actions (create_item/send_webhook/post_chat/notify_user/send_email) run on itemless events — `_run_rule_actions` skips only `ITEM_ACTIONS` (lines 492-499; `types.py:66-121`). *Fix: drop the parenthetical; item actions skip-log, universal actions run.*
- **MEDIUM** — `server/src/radd/modules/timelogging/service.py:327-335` — `authorize_mutation`: says author-with-`worklog.write` may delete. The delete arm is now purely relation-resolved against `worklog.delete` (lines 344-355; "The hardcoded author arm is gone") — an author holding only `worklog.write` can be refused. *Fix: edits = author+write or `others`; deletes = `worklog.delete` relations (Baseline grants `@own`).*
- **LOW** — `automations/engine.py:483-487` — `_run_rule_actions` enumerates universal actions without `send_email` (handled at engine.py:290, in `UNIVERSAL_ACTIONS`).
- **LOW** — `automations/engine.py:170-171` — `_Plan.http` documented/annotated as "(url, json_body, headers)"; the stored triple is `(url, body, secret: str)` (lines 274, 281, unpacked at 402). *Fix: annotate `tuple[str, dict[str, Any], str]`.*
- **LOW** — `items/slq/compiler.py:98` — `_plugin_condition` documents `item_ids(contains, value)`; the contract is three-argument `(contains, value, ctx)` (`kernel/specs.py:71-72`, call site compiler.py:111-115).
- **LOW** — `kernel/plugin.py:5` — "All 49 builtin plugins" — 53 modules construct `RaddPlugin` today. *Fix: drop the number.*
- **LOW** — `items/service/core.py:86` — comment "append to the bottom of the manual order"; `_next_rank` returns `min(rank) − step` (`items/service/queries.py:282-286`) and listing orders `rank ASC` — new items land at the **top**.

Clean on specific claims: `auth/authz.py` (incl. `require_anywhere`), `views/service.py`, `ai/service.py`, `mcp/tools.py`, `events/service.py`, `events/runner.py`, all of `kernel/` (bar the count), `items/service/*`, `items/slq/*` (bar one), `notify/`, `comments/`, `pages/links.py`.

### FastAPI endpoint descriptions

- **HIGH** — `server/src/radd/modules/views/router.py:111-115` — `PUT /views/{id}/sharing` description: "Replace the view's FULL sharing state … + per-user/team grants at viewer|editor." `ViewSharingUpdate` carries **only `global_access`** (`views/schemas.py:124-128`); per-subject grants moved to `/grants` (spec 92). *Fix: "Set the view's public access level; per-subject grants via /grants".*
- **MEDIUM** — `items/router.py:326-327` — `DELETE /items/{item_id}`: "project.manage; children must be removed first." The gate is `Permission.ITEM_DELETE` (`items/service/core.py:311-313`; spec 50). *Fix: "item.delete (project.manage implies it)".*
- **MEDIUM** — `mcp/router.py:3-4` — module docstring (which the POST handler defers to): "JSON-only … no SSE streaming." `GET /mcp` (router.py:109-126, RADD-740) returns a `text/event-stream` `StreamingResponse`. *Fix: POST is JSON-only; GET is the SSE notification stream.*
- **LOW** — `items/router.py:283` — `POST /items/{item_id}/links`: "(blocks/relates/duplicates)" reads as a fixed enum; `link_type` is a spec-91 catalog key incl. custom types, auto-managed types refused (`items/service/links.py:192-208`).
- **LOW** — `views/counts.py:37-38` — service docstring says "global item.read"; the gate is item.read in ≥1 project (`readable_projects`, lines 54-56; the RADD-788 fix comment sits directly below).
- **LOW** — `attachments/router.py:4-6` — module docstring: page parents → "global doc atoms" (now space-scoped, RADD-791, `pages/attachments_binding.py:29-45`); delete "uploaders remove their own, admins anyone's" (now relation-resolved `attachment.delete`, RADD-816, router.py:134-154).
- **LOW** — `sso/router.py:37-38` — "only their label/kind" — the payload is `id`, `name`, `kind` (`sso/schemas.py:102-107`). Mirrored client-side (see section c).

~25 sampled endpoints verified accurate, including `/views/{id}/transfer`, `/auth/view-as`, `/users/directory`, `/users/{id}` PATCH/DELETE, `/releases/{id}/sweep`, `/worklogs`, `/search/semantic`, `/projects` (RADD-672), `/timesheet`.

---

## (c) Lying comments + stale TODOs

### Backend comments

- **MEDIUM** — `server/src/radd/modules/auth/service_accounts.py:30-31` — "a service account is never mistaken for a person and never gets notified." Three verified contradictions: (1) `GET /users/directory` (`auth/router.py:339-359`) applies no source filter and `UserDirectoryEntry` (`auth/schemas.py:73`) omits email *and* source, so pickers render a service account exactly like a colleague; (2) `_resolve_assignee` (`items/service/relations.py:77-93`) refuses only inactive accounts, and nothing in `notify` filters `UserSource.SERVICE` — assigned service accounts get notification rows (only SMTP delivery is inert); (3) `ServiceAccountCreate.email` (`auth/schemas.py:350`) accepts any real address, defeating the synthetic-domain mechanism (`service_accounts.py:64`). *Fix: scope the claim to "cannot log in; default address undeliverable" — or make it true (badge/exclude SERVICE in the directory, reject non-synthetic emails).*
- **LOW** — `comments/models.py:41` (echoed `comments/router.py:64`) — "Resolve, never delete." `DELETE /comments/{comment_id}` → `service.delete_comment` (`comments/service.py:382-390`) has no guard on anchored/resolved threads. Design preference stated as behavior. *Fix: reword, or actually guard anchored-thread deletion.*

### Frontend comments / prop docs

- **MEDIUM** — `web/src/components/items/VcsPanel.tsx:30-33` — "Populated automatically by connectors (GitLab/GitHub) later …; for now links can be added manually." The "later" shipped: `vcs/service.py:63` `upsert_vcs_link` is called by `gitlab/router.py:64`, `forgejo/router.py:93`, and the spec-111 backfill (`forgejo/backfill.py:106`). Also names GitHub — no GitHub connector exists; the pair is GitLab/Forgejo. *Fix: describe auto-population as the normal path.*
- **MEDIUM** — `web/src/components/Modal.tsx:17` — JSDoc: "focuses its first form control on mount." The querySelector (lines 29-31) includes `button` and the header's X precedes the body, so the X close button is always focused — `ConfirmDialog.tsx:32-39` explicitly works around exactly this. *Fix: document reality; callers focus their own control.*
- **MEDIUM** — `web/src/components/settings/TeamPanel.tsx:49` — JSDoc: "A directory-linked team's roster is read-only — AD owns it (spec 87)." Superseded by RADD-829 in the same function (lines 56-58: membership always hand-editable; `TeamSource` retired, `teams/types.py:27-29`). *Fix: delete the sentence.*
- **LOW** — `web/src/components/Select.tsx:28` — prop doc "md = h-8 px-2.5 … (matches TextField)"; actual `pl-2.5 pr-7` (line 43) — matches TextField only in height/text.
- **LOW** — `web/src/components/TokenMultiSelect.tsx:38` — "Enter/comma to add" stated unconditionally; comma only fires with `allowCreate` (default false) and commits raw text, never the highlighted option (lines 118-120, 186-191).
- **LOW** — `web/src/lib/constants/api.ts:172` — "label + kind only" for `/auth/sso/providers`; payload is id + name + kind (same drift as the server-side docstring above).

Verified-true sample (auditable): 17 backend + 15 frontend strong claims checked and found accurate — including `forms/portal.py:44` "only caller", `sso/service.py:336` "only branch that CREATES an account", `forgejo/schemas.py:40` "credentials never returned", `slq/compiler.py:108` "`me` never reaches the resolver", peek 1100px, Backlog-always-last, CommandPalette Ask-never-closes, ConfirmDialog resolution semantics.

### TODO/FIXME/XXX/HACK inventory

**Empty.** Every grep hit in `server/src/radd` and `web/src` is a false positive (`StateCategory.TODO` enum members and "todo" as a category name in prose/data). No deferred-work marker exists in either tree. Age caveat: history was squashed on 2026-08-02, so all lines blame to the root commit; pre-squash comment age is unrecoverable. The three "for now" comments found: `views/models.py:90` and `web/src/lib/axis-dnd.ts:194` still accurate; `VcsPanel.tsx:32` is the finding above — the one confirmed "for now" that outlived its truth.

---

## (d) Doc-file drift

### docs/plugin-ui.md
- **MEDIUM** — `docs/plugin-ui.md:225-226` — the file ends with literal stray tool-call markup (`</content>`, `</invoke>`) checked in. *Fix: delete the two lines.*
- **LOW** — `docs/plugin-ui.md:48` — `dashboardWidget` props documented as `{config, widget}`; the SDK's own comment (`web/packages/plugin-sdk/src/slots.tsx:65`) says `{config}`. One side is wrong. *Fix: align with what `WidgetCard.tsx` actually passes.*
- Everything else concrete verified true: all 14 `SlotId` values, contribution shape, all 10 host-anchor files, both settings endpoints, SDK exports, `examples/acme-notes/`, `build-all.mjs`, bundle serving path.

### docs/plugin-platform.md
- **MEDIUM** — a "Status: design" doc whose "today" anchors are several waves stale, while line 12 pitches it as the platform reference: line 4 "45 in-repo modules" (54 now); line 154 cites `attachments/storage.py` (deleted, spec 102); line 164 says `automations/catalog.py` hardcodes `_SPECS` importing 21 modules (inverted — it now derives from `kernel.registries` and says so); line 345 "the SPA has no plugin seam … no capabilities endpoint" (spec 94 built both; `modules/capabilities/` exists); lines 376-378 "no line between public API and internals" (`server/src/radd/sdk.py` is the line); §10's proposed plugin manager exists (`modules/pluginmgr/`). *Fix: add a "partially built — specs 93/94/113/114" banner and mark the shipped phases.*

### docs/deploy.md
- **LOW** — `docs/deploy.md:15` — "unless you point `RADD_ATTACHMENT_STORAGE=s3` at an S3/MinIO bucket" reads as if env is the live switch; since spec 102 env only seeds the first storage-host row (the doc's own lines 26-28 say so) and MinIO is archived for Garage. *Fix: "seeds the first storage host; Settings → Storage owns it afterwards."*
- Everything else verified true — an unusually clean doc (compose profiles, Garage init, pgvector image, backup CLI + env defaults, TOTP routes, the full env-reference table, helm probe path).

### docs/contributing.md
- **MEDIUM** — `docs/contributing.md:31-32` — "`test_merge_coverage` currently flags `view_members.added_by`; that failure is known and not yours." Stale: the file passes (12 passed) and `("view_members", "added_by")` is in `_MERGE_REPOINT` (`auth/service.py:536`). Telling contributors to ignore a failure that no longer exists trains them to ignore a real one. *Fix: delete the paragraph.*

### README.md
- **MEDIUM** — `README.md:41-42` — the Jira sample-import command passes `--workspace main`; `server/scripts/import_jira.py` removed that flag (spec 86 — its own docstring, line 9, says the workspace entity is gone). The documented command exits with an argparse error. Same command also appears in CLAUDE.md's Running section. *Fix: drop `--workspace main` in both.*

### PLAN.md (§8/§11 sample)
- **MEDIUM** — §8 "authoritative status" self-contradicts and contradicts code: line 208 "SSO, wiki, extensions, AI still untouched" vs its own "ALL landed (specs 43-48)" ~40 lines later; lines 220/225 still describe the eradicated workspace settings scope; line 234 says WYSIWYG is "Milkdown/Crepe" (Crepe removed, RADD-745).
- **MEDIUM** — §11 lines 301-306 present "Current runtime state … 625 core tests green; alembic head `5e4a41d09ca0`" as current; the suite collects 1570 and CLAUDE.md routes readers here for current state. *Fix: date-stamp these blocks as historical, or refresh.*

---

## (e) CLAUDE.md claims now false

1. **HIGH** — "Latest: 0.9.0 — … LIVE on project.radd-hq.com" and the "Branch `kernel-plugin-platform` (specs 93-114)" header. Newest tag is **v0.21.0** (then v0.20.0, v0.19.0, v0.18.1…); only `main` exists — no `kernel-plugin-platform` branch. Twelve releases (incl. the spec-115 access-control wave) have no CLAUDE.md coverage. *Fix: rewrite the status preamble; consider moving volatile counts out of CLAUDE.md entirely.*
2. **MEDIUM** — "Tests 1335." `pytest --collect-only` collects **1570** (1257 `def test_` across 141 files + parametrization).
3. **MEDIUM** — "`/health` is the health endpoint (unprefixed)." No `/health` route exists anywhere in `server/src/radd` — every router mounts under `settings.api_prefix` (`app.py:74-82`), no health handler is registered, and `GET /health` falls through to the SPA catch-all returning index.html. Helm probes use `/api/v1/instance/login-options` instead. *Fix: delete the sentence or build the endpoint.*
4. **MEDIUM** — Repo-layout bullet "compose.yaml — dev Postgres (app Dockerfile/compose services + Helm chart are still to build)." compose.yaml's first service is `app` built from `Containerfile`, and `deploy/helm/radd/` exists. Spec-48-era parenthetical.
5. **MEDIUM** — Running section's Jira import command carries the removed `--workspace main` flag (see README finding; the command errors).
6. **LOW** — "Fifteen browser proofs in web/scripts/" — now 23 `*-proof.mjs`.
7. **LOW** — "Trigger snapshot 67" — `server/tests/_trigger_catalog_snapshot.json` holds 70.
8. **LOW** — "Tests 1288 (`test_sso_providers.py`, 22)" — the file now has 32 test functions.

**Verified true** (auditable sample): zero raw `zinc-*`/`indigo-*` Tailwind utilities in web/src (7 grep hits, all comments or `--chart-*`-story hex constants); `@milkdown/crepe` gone from web/package.json; `.mcp.json` registers `radd` → `https://project.radd-hq.com/api/v1/mcp`; every cited file exists (`clientip.py`, `render-proof.mjs`, `chrome.mjs`, `test_route_shadowing.py`, `milestones/mcptool.py`, `editor-style-baseline.json`, `carddesigner/`, specs 110-114, `sdk/`, `research/`); all five spot-checked `RADD_*` env vars exist; Postgres on 5455; `pgvector/pgvector:pg16`; `--profile storage` + `deploy/garage/init.sh`; seed flags; every narrative route checked (`/releases/{id}/sweep`, `/grants`, `/auth/sso/providers`, `/fields/writable`, `/search/semantic`, `/ai/similar`, `/views/card-presets`, `mcp_project_enum_max`). Skipped as not cheaply verifiable: bundle size delta, in-cluster Garage topology, the historical "9 → 19 tools" delta (live server now surfaces 24 MCP tools, consistent with growth).

---

## Suggested triage order

1. `merge_users`/`delete_user` docstrings (data-retention lie) and the service-accounts comment (identity/notification lie) — both misdescribe security-relevant behavior.
2. CLAUDE.md preamble rewrite (fixes six findings as a class) + the two copies of the broken `--workspace` command + the `/health` sentence.
3. docs/modules.md: the three high rows (line 156 gaps, ai row, views row), the wrong workflow event names, and a one-pass depends-cell refresh (consider making the cells track real imports, or fixing the modules' own `depends_on` tuples at the same time — items, mcp, forgejo, views are wrong in code too).
4. contributing.md stale known-failure paragraph (actively harmful to contributors) and the endpoint descriptions (`/views/{id}/sharing`, `DELETE /items/{id}`, MCP transport).
5. plugin-platform.md "today" anchors banner; PLAN.md §8/§11 date-stamping; the low-severity comment/prop-doc fixes.
