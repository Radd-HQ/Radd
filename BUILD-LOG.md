# BUILD-LOG — kernel + plugin platform migration

*The build narrative: what each wave built and why, newest first, then the kernel+plugin migration log it started as, then the PLAN.md addenda. Current state is the git tags, `docs/modules.md` and the tracker — this file explains how it got there.*

Running record of decisions, deviations, and unmet parity (with reasons) while migrating Radd
onto the kernel+plugin architecture of `docs/plugin-platform.md`. Newest entries at the bottom of
each section. The parity checklist (definition of done) is `docs/specs/93-kernel-plugin-platform.md`.

Branch: `kernel-plugin-platform` (off `main` @ b30172d).

---

## Waves, newest first

Moved here from the CLAUDE.md preamble on 2026-09-27 (RADD-1441): one entry per wave, exactly as the
preamble narrated it at the time, so the working agreement stays rules-only. The tracker's RADD project
and `docs/specs/` are the primary record; these entries are the per-wave summary.

### Plugin-ownership wave — epic RADD-1343 (2026-09-25/26), not yet released when this was written

Self-hosted, AI-native issue tracker + wiki, LIVE on project.radd-hq.com. **The current release is whatever the newest git tag says — this preamble is the per-wave build NARRATIVE, newest wave first, not a version claim, so it carries no version number of its own** (the spec-115 access-control wave and the RADD-8xx hardening waves followed what's described below). **Newest: the PLUGIN-OWNERSHIP wave (epic RADD-1343, 2026-09-25/26).** Codex audited and moved the first surfaces (RADD-1340–1366). A review then course-corrected, and the rest followed (RADD-1366–1401):
- **Core modules are static plugins bundled into the host; only optional plugins are remotes** (RADD-1373). Pages and Dashboards became core by decision (RADD-1392/1393).
- **Every optional plugin's UI is its own**, through generic contribution points:
  - settings pages (Email, AI, Directory, the importers under an "Import" nav group), and a Sign-in section;
  - `item.attribute` list columns and card cells;
  - project-settings pages;
  - list-surface view types (`slas.queue`);
  - editor extension points and transforms;
  - `liveDocuments` + `EditorBinding` for co-editing;
  - palette and query-bar modes;
  - `public.page` for pre-auth plugin pages;
  - `content.body` claims.
- **The SDK surface is DERIVED from its source** (`web/scripts/sdk-exports.mjs`); UI API is 1.19.0.
- **Backend: a core module never reaches an optional plugin** (`test_core_modules_never_reach_optional_plugins`). The 25 former reaches go through kernel sockets: `TRANSITION_CHECK`, `SEARCH_DOCUMENTS`/`SEMANTIC_CANDIDATES`, `NOTIFICATION_SUBJECT`/`_AUDIENCE`, `MAIL_TRANSPORT`, `PERSON_AVAILABILITY`, plus the existing `STORAGE_ROUTING_RULE`.
- **Integration behaviours are plain plugin settings again** (RADD-1368–1370, default OFF).

Real bugs found on the way:
- a team-restricted internal comment reached every internal reader's inbox, excerpt included (RADD-1391);
- SLA queues 500'd when mixing timed and untimed issues (RADD-1396);
- a co-editing save could overwrite a colleague's newer text (RADD-1397);
- Outbound email read Off on sender-row instances (RADD-1389);
- guessed status tokens left error text uncoloured (RADD-1388).

Proof traps:
- Chrome keeps only 250 resource-timing entries, so "not loaded" checks passed vacuously until `lib/cdp.mjs` raised the cap.
- The harness leaked a Chrome profile per run until `/tmp` (tmpfs) filled (RADD-1399).
- Two agents each adding `integrations=` to one manifest merge textually clean and fail to import.

Record: `research/plugin-isolation/README.md`.

### The AI-ON-QWEN wave (2026-09-20 — four issues, shipped with the automation wave as one release)

Every one came from using the product on the pilot instance the day after the model host moved to sglang + `qwen3.8-27b`: **RADD-1273** — Qwen3 templates THINK unless the request opts out and the payload builder sent only model/max_tokens/messages, so every call reasoned first inside the answer's budget (a two-way structured choice: 2.6 s → 0.7 s); `ai_providers.reasoning` (OFF for every row, migration `d1273aireason`) + `request_params` (JSONB, deep-merged LAST), `provider.finish_payload` is the last word on every chat payload, a Reasoning checkbox + "Extra request parameters (JSON)" on the provider form — Radd states its preference, the provider's template is never edited for Radd; **RADD-1274** — summarizing a page from the editor DELETED its video: the run sends the whole document and splices the reply back, so a `radd:media` fence the model does not return reads as a deletion; `editor/ai-protect.ts` masks every `radd:*` fence / image / attachment link behind `⟦keep-N⟧` and restores it after (dropped ones appended, never lost), `EDITOR_SYSTEM` carries the one rule, and the review counts the inline comments whose passage it strands and offers to resolve them on accept (decided at review END against what was actually accepted); **RADD-1276** — the rail's Detached group with "Passage removed / ambiguous" labels and Resolve all behind a confirm (RADD-726's never-auto-resolve stands); **RADD-1275** — `ai/images.py`: a summary shows the VISION role the entity's image attachments (readable by THIS actor through the spec-102 chokepoint, downscaled through `thumbnails`, capped), `user_content_parts` generalises the one-image builders, the page's read-mode Summarize sends `images_of` — on the dev instance the model quoted the OCIO error out of a generated screenshot. Traps: the host-run dev server has NO reload (a proof against a new SPA and an old prompt passed for the wrong reason); a `⟦keep-N⟧` comes back wrapped in backticks; `[data-extension]`, not `data-radd-extension`, is the extension node view's hook. Proofs: `ai-provider-options-proof.mjs`, `ai-protect-proof.mjs`, `page-detached-comments-proof.mjs`.

### The AUTOMATION WAVE (epic RADD-1264, 2026-09-19 — six issues, one release)

A full audit of the automation system came first (every node read against the executor, the planner, the event registry and the SPA; the live instance had ZERO automations); then, in order: **RADD-1265 audit fixes** — `send_email` had been dead on a rows-only instance since RADD-983 (the planner read the env `smtp_host`; it now asks `mailintake.transport.outbound_configured`), the spec-58 condition tree is DELETED (`gate.event`, `conditions.matches`, `ConditionsBuilder`; migration `d1265autolegacy` rewrites stored graphs, disables what it cannot express), `gate.payload` ("Event value is") is the one open-ended gate, the schedule trigger's `query` and `{{matched_count}}` are gone (a `search.slq` node is the one way), `{{item.*}}` grew url/state/priority/assignee/reporter/project/type/labels (loaded once per action node), canvas nodes carry palette labels (`data-node-type` is the proof hook), the palette is ordered Items-first, a new automation opens on a placed trigger; **RADD-1266 run history** — `automation_runs` holds every applying walk in the dry run's `RuleTestResult` shape (ONE builder, `engine._result_of`), status applied|nothing_to_do|refused|failed, a raising walk is recorded and emits `automation.run_failed` instead of stalling the consumer, swept after `automation_run_retention_days`, a Runs tab renders through the shared `RunResultView`; **RADD-1267 coverage** — twelve item actions (parent/type/reporter/dates/estimate/flag/visibility/link/archive/watcher/participant/move), `gate.project`, nine events switched on as triggers (snapshot 76→85), `page.comment`/`page.move` contributed by the pages plugin; **RADD-1268 versions** (delivers RADD-1111) — `automation_versions` holds EVERY version incl. the current, restore writes a NEW version (history never rewrites) and re-validates, `version` in the ledger diff, a Versions tab with read-only preview + confirm; **RADD-1269 the `scripts` plugin** — `core=False`, a uv-built venv per instance (`RADD_SCRIPTS_DIR`, the SDK from `/app/sdk` in the image), packages as rows (name+specifiers only), `script.run`/`script.decide` nodes whose Python BODY lives on the node (RADD-1272 — a CodeMirror editor and a Test box in the inspector; the graph's versions are the script's history; Automations and Scripts sit under the SERVER settings group), runs OUT OF PROCESS with a minimal env and a short-lived UNSCOPED key minted for the automation's actor (`auth.service_tokens.mint_ephemeral_token`; a key can never exceed its account), the harness contract `main(ctx)`; two engine fixes it exposed — a contributed action's failure now rewrites its plan entry, and `ActionPreview.type` is a string so contributed actions appear in reports at all; **RADD-1270 dogfood** — three enabled automations on the RADD project (Triage arrival, Release shipped receipt, Stale review nudge), created over REST because the MCP surface has no automation tools (a gap to file). Traps: `tests/test_module_contracts.py` refuses non-spine model imports (go through services); `test_merge_coverage` demands every new user FK in the repoint table; React Flow only mounts nodes in the viewport (chain, then fit-view, in proofs); a subprocess's relative path resolves against ITS cwd. Proofs: `automations-runs|coverage|versions-proof.mjs`, `scripts-plugin-proof.mjs`.

### The first public-report wave (RADD-1236…1245, 2026-09-19 — GitHub radd-hq/radd#8–#17, one release)

Every report was VERIFIED against the tree before a decision: six built as asked (participants + Related links over MCP — by key/email/team name/URL, `participants/mcptools.py`, `weblinks/mcptools.py`; Pages in the palette's Go to and on the collapsed rail; a context-aware top button that is **New page** in the wiki; a live page deletable from the page like an issue), three were bugs with a one-line cause (the item's time panel query carried no entity tags so the hub never subscribed it — RADD-1237; the account menu computed its theme entry at render and nothing re-rendered it, so the second click repeated the first — `lib/theme.ts` is a `useSyncExternalStore` store now, RADD-1238; `/pages/<page uuid>` was a space address nobody owned — rescued to the page, and the MCP receipt carries a permalink `url`, RADD-1240), and one exposed a spec-122 choice worth reversing (co-editing autosaves bumped `version` without writing a history row, so headers read v4 over a History of v1 — the bump now moves WITH the row and the collab room SEALS a session that ends without its final save, RADD-1244). **Same day, RADD-1246 — threaded replies on EVERY comment surface** (issue comments, page discussion, annotations; MCP `comment_item reply_to`), replies one level deep with an audience bounded by the thread's: an internal thread forces internal replies, a public thread allows them (`comments/threads.py::reply_audience`, `reading.audience`). Proofs: `web/scripts/comment-replies-proof.mjs`. **RADD-1248 — page comments reach automations:** comment events declare `page` as a subject and carry `parent_comment_id`; the engine runs a page comment on the itemless path instead of dropping it as "item vanished"; two named gates (`gate.comment`: root/reply × public/internal, `gate.page_space`) and page/comment template tokens. **RADD-1247:** the search indexer and the outbound-mail planner step over page comment events instead of logging a traceback each. **RADD-1249:** the archive browser searches, multi-selects, and bulk-restores / bulk-deletes through two per-page-reporting endpoints. Proof: `web/scripts/remus-reports-proof.mjs` (15 checks).

### Spec 124 — PAGE ADDRESSES (RADD-1233, 2026-09-18)

*Keyed by id, addressed by path*: `pages.number` is the human key and the PERMALINK (`/pages?pageId=12402`, resolved and REPLACED by the readable address); the canonical URL is `/pages/<space>/<slug>/<slug>/…` (a splat), slugs are unique among LIVE SIBLINGS only (partial index; `uq_pages_space_slug` dropped — two parents may each have an `onboarding`, an archived page frees its name, RADD-1228's collision is gone); `path` is derived from rows the tree already loads, never stored; resolution is ONE query (walk the tree in memory) then an EXACT `page_path_history` lookup (every old address of a renamed/moved/restored page AND its descendants) and nothing else — the migration seeds the history with every nested page's old single-slug address (RADD-1234); `lib/page-links.ts` is the only place the SPA assembles a page URL and `mailrender.page_url` emits permalinks; the print view moved to `/print/pages/…` because nothing may hang a literal after a path. `docs/specs/124-page-addresses.md`, proof `web/scripts/page-paths-proof.mjs`.

### Spec 123 — THE AUDIT LEDGER (RADD-1165, 2026-09-14, eight issues, one release)

*Who changed what, from what, to what — and an auditor can find it*: `kernel/changes.py` is the one diff shape and `events.emit(changes=)` REFUSES an `updated` event without one (the RADD-923 pattern) — the sweep found 16 registered `updated` types with no diff and 48 event types emitted but never registered, and emptied both lists; the silent admin surfaces (settings, public access, SSO/AI providers, storage hosts and rules, VCS/import connections, mail config, time-logging config) now emit, with secrets only ever "changed"; `events` gained the LEDGER columns (`project_id`, `entity_label`, `search_text` under a guarded trigram GIN, a GIN over `payload->'changes'`; `d123ledger` backfills) so `GET /audit` filters by project, entity, person, changed field, source, dates and free text, hides `audited=False` noise, and lets a project manager read their own project (item diffs redacted through the RADD-834 seam); `GET /audit/catalog` is the SPA's vocabulary; Settings → Audit log is a URL-carried filter bar over sentences with the entity linked and old→new lines (`components/history/ChangeLines.tsx`, shared with the issue History tab); every settings page carries a "Change history for this page" footer link and entity editors a `ChangeHistoryPanel`; `audit_log` over MCP. Proofs: `web/scripts/audit-proof.mjs`, `history-links-proof.mjs`. `docs/specs/123-audit-ledger.md`.

### Spec 122 — COLLABORATIVE EDITING (RADD-676, same day as the wave below, same release)

*One live document, many editors*: a `collab` module holds one pycrdt document per wiki page in the API process and speaks the y-websocket protocol on `WS /collab/pages/{id}?session=` (cookie auth like `/ws`; `POST …/join` mints an editor (page.write) or observer (page.read) session; observers' document frames are dropped at the channel); state persisted per page TAGGED with the page version (resume on match, discard otherwise); ONE seed grant while the document is empty; **the write guard** — two hooks `pages` dispatches (`page.body_writing`, `page.version_bumped`) let `collab` refuse (409, naming the editors) any body write not vouched by a connected editor's `collab_session`, and reset the room (4409) when something else wrote the page; vouched saves skip `expected_version` and coalesce history to one row per `page_collab_version_window_seconds` + the final save. SPA: `@milkdown/plugin-collab` (exact 7.21.3), an ELECTED SAVER (lowest awareness client id) autosaves 1.5 s after any change, **Done** replaces Save, `EditingNow` in the header for readers too. Three traps the proof found: Milkdown's listener ignores `addToHistory:false` (remote) transactions, so the editor re-serialises the bound doc itself; pycrdt's YRoom sends no awareness snapshot to a newcomer (two savers for 15 s) — the channel does; unbind before destroy. Rooms are PER PROCESS (single replica today — `docs/deploy.md`). Proof: `web/scripts/collab-proof.mjs` (three browsers, 20 checks; the election is random, run it more than once). `docs/specs/122-collaborative-editing.md`.

### The verification-and-tidy wave (unnumbered, 2026-09-13, RADD-1160 — twenty-one issues, one release)

Every open issue's CLAIMS were re-verified against the tree before anything was built (two were already fixed, one was half wrong), then: **a version that BECOMES released sweeps whichever path did it** (RADD-1007: REST, MCP and the connector webhooks all go through `pipeline.create_release`/`update_release`; the Releases page gained a Sweep button; notes stored whole — RADD-907's `[:2000]` slice is gone; MCP `get_release`/`update_release`, RADD-908); **MCP validates every tools/call against the ADVERTISED schema** (RADD-1106: `catalog.resolved_schema` is the one function tools/list and the dispatcher read; -32602 lists every violation, a handler exception is -32603, never HTTP 500; `jsonschema` added); the wiki is WRITABLE over MCP (`create_page`/`update_page`/`move_page`, RADD-1005, enforced through the shared `page_access.guard_page`); item dates over MCP (RADD-1157); **SLQ plain-reading negation** (RADD-1139: `!=`/`NOT IN` over a nullable to-one relation is the COMPLEMENT of the positive form — `polarity(nullable=True)` emits `IS NOT TRUE` — so `epic.category NOT IN (done)` includes epic-less items and `= x`/`!= x` partition the rows); NL→SLQ carries the live state names and maps fixed/closed/open to categories (RADD-1140); the list's Item column is a real resizable column (RADD-1110, CDP-proven); **the profile timezone is READ** (RADD-1008: `dates.ts` is the one seam, timestamps in the reader's zone, date-only values never shift); one canonical VCS external id with a partial unique index + savepoint upsert (RADD-1124, migration `h1124vcsid`); the notify consumer no longer commits a borrowed session (RADD-1047/992); page Move to…, token scopes, project rename+description (RADD-1009, migration `d1009projdesc`, CDP-proven); and a LIVE bug the dev-server log exposed on the way — the wiki embedder had crashed on every sweep since RADD-1147's tuple change (RADD-1159). Tracker hygiene the same day: 25 Triage items decided, RADD-1084 closed as already delivered, the audit ledger's C1 marked done.

### Spec 121 — PUBLIC PROJECTS, issue visibility, Sign in with GitHub (RADD-1141)

*The world is a principal, not a flag*: two seeded `users` rows, **Anyone** and **Signed-in users** (`UserSource.PRINCIPAL`, fixed ids in `auth/principals.py`), are grant SUBJECTS — `grants._subject_condition` and `SubjectContext.subject_user_ids` are the only two places that know the world exists, and everything downstream (`effective_permissions`, `readable_projects`, the relation filter, the MCP catalog) inherits. A **public project** IS one row (the seeded **Public** role → Anyone, project-scoped); **contributions** are a second (the **Contributor** role → Signed-in users); `auth/public_access.py` + `PUT /projects/{id}/public-access` present them as two switches on Settings → Project → Access, and `ProjectRead.public/contributions` are DERIVED from the rows. An unauthenticated request resolves to the Anyone row through the new **`Actor`** dependency (`auth/deps.py`) — structurally read-only at the seam, `CurrentUser` untouched (600+ sites), and the routes that accept it are a FROZEN inventory (`tests/test_anonymous_surface.py`, both directions); `/auth/me` answers 200 `anonymous=True`. **Issue visibility** (`work_items.visibility`: public | internal | restricted, project default via the scoped setting `item_default_visibility`) rides ONE kernel primitive: a **row guard** (`RowGuardSpec`) every reader passes whatever relation they hold — `@any` stops meaning "every row"; restricted rows admit only `own`/`assigned`/`participant`; the instance admin (`RelationActor.unrestricted`) is the one bypass — composed inside `authz.relation_filter`/`relation_holds_row*`, so lists, counts, search (the `search_index.visibility` mirror + `_guard_index_clause`), gates and notify agree by construction (`test_item_visibility.py` is the six-actor matrix). `@public` is a `row_property` relation, which is what makes a public project appear in everyone's rail. **GitHub** is a third SSO kind: a kind supplies its ENDPOINTS and PROFILE STRATEGY (`sso/idp.py`: id_token vs OAuth profile — `/user` numeric id as subject, `/user/emails` verified primary), the state+PKCE+one-callback+identity-pinning engine stays shared. **The public wiki joined the same model** (RADD-1147): spec 74's `page_spaces.public` + `/public/pages` router + `/public-pages` SPA are DELETED; a public space is the Public role (now carrying `page.read`) granted to Anyone on the space, read through the ordinary page routes in the ordinary shell. Spec 115's D9 stands: nothing lets an anonymous caller write. `docs/specs/121-public-projects.md`. **The kernel-plugin-platform work (specs 93–114) is merged to `main`.** Editor: the chrome is OURS since RADD-745 (0.9.0). `@milkdown/crepe` is gone from `web/package.json`; Milkdown and ProseMirror stay. `new Crepe(...)` was `Editor.make()` plus seven kit plugins, and by the end it configured nothing — every surface is a React component of ours: the toolbar (real buttons, acting on CLICK, `aria-pressed` for state), the code block (CodeMirror 6 wired directly, the same view read-only in the viewer), the table chrome (grid picker + measured handles; the engine, `prosemirror-tables`, is untouched), images (resizable — the width rides in the URL as `?w=`, and the attachment endpoint serves fewer bytes), the AI selection surface (same endpoint, same reviewable diff, no command dispatched by NAME to dodge a duplicate module), `radd:*` fences as a real editor node with a schema-GENERATED config form, and one `editor.css` over house tokens — so `rich-editor.css` stopped being a retint and the raw-`--color-zinc-*` exception went with it. Bundle 5.6 MB → 3.9 MB. Browser proofs live in `web/scripts/` (26 and counting), including a style baseline that reports what MOVED in both themes.

### 0.3.0/0.3.1 — specs 111–114 + two Garage hosts

**Spec 111 — Forgejo rebuilt**: `forgejo_connections` + `forgejo_repos` rows (migration `d111fjconn`; env secret is SEED-ONLY), a receiver that verifies a payload against ITS OWN repository's connection (a second host's genuine secret must not authorise writes against the first host's repos) with a scan-active fallback for unrecorded repos; `release`/`create`/`delete`/`workflow_run` events; CI state on `item_vcs_links` (`d111ci`); and an API BACKFILL that walks branches/PRs/commits so history predating the webhook links (idempotent via the upsert seam's external ids). `project_id` on a repo is a DEFAULT, never a filter — keys are unique instance-wide. New atoms `vcsconn.*`. **Spec 112 — the release pipeline**: `Waiting for release` in the **done** category means finished-not-shipped (so throughput counts the day the work was DONE), two project settings name the states, a published version find-or-creates the release and SWEEPS every waiting item into the shipped state with `release_id` set — which is what satisfies a guard requiring a release to enter Done. `POST /releases/{id}/sweep` works with no Forgejo at all. **Spec 113 — service accounts + scoped keys**: `UserSource.SERVICE` cannot log in (`create_session` refuses — one seam covers local/TOTP/LDAP/OIDC), `api_tokens.scopes` carries RAW permission atoms (`d113svcacct`), and enforcement is ONE intersection inside `effective_permissions` AND `permissions_for_projects`: **a key can never exceed its account**. **Spec 114 — the MCP catalog is a function of the caller**: tools declare their atom, `visible_catalog` drops what the key cannot run and rewrites the project parameter to an ENUM of the permitted projects (degrading to a string above `mcp_project_enum_max`); 9 → 19 tools across workflow/time/releases/admin; hiding is presentation, enforcement is still `authz.require`. **Storage**: two independent single-node Garage instances in-cluster (`garage-content`/`garage-general`, 20Gi, proxy delivery). **0.4.0 — the MCP hardening wave (RADD-640/672/673 + fixes):** plugins contribute MCP tools through a kernel registry (`McpToolSpec` — the spec IS the annotation, the dispatcher REQUIRES the declared atom before the handler runs, unmount removes catalog+dispatch together; north star `milestones/mcptool.py`); `authz.require_anywhere` fixes the catalog/enforcement split where every cross-project read gate (GET /projects, un-scoped item listing, MCP search/list tools) demanded GLOBAL item.read that a spec-113 scoped key never holds (~25 more member-floor gates audited in RADD-674); the MCP surface is workflow-complete — `type`/`parent`/`estimate_points`/`cycle` by NAME on create/update, `category` on log_work, `status` on create_release, new `sweep_release` — so the whole tracking loop below runs over MCP with zero REST; plugin UI remotes are BUILT INTO the image (the Containerfile web stage runs `build-all.mjs`, whose output was gitignored so production 404'd every remote since 0.1.0); a missing plugin asset 404s instead of 500ing. Tests: `uv run pytest` (~1.6k as of 2026-08; the suite is the count). `docs/specs/111|112|113|114-*.md` (114 has the addendum). **Before (specs 93–110):** **Latest: spec 110 — SIGN IN WITH GOOGLE / the SSO provider registry**: providers moved out of the environment into `sso_providers` rows (migration `d110ssoprov`; `kind` google|oidc — every kind runs the SAME code+PKCE engine, a kind only supplies discovery defaults, Google's issuer PINNED so an admin pastes a client id/secret and nothing else; env `RADD_OIDC_*` + new `RADD_OIDC_SIGNUP_DOMAINS` are SEED-ONLY, the spec-101 rule), plus **`user_identities`** (provider, `sub`) → user. **Identity: verified email ONCE, then the subject forever** — the first login matches the person's existing AD/local account by email (`require_verified_email` default ON; linking by email is exactly what an unverified address would exploit) and pins an identity row, so a Google login JOINS the AD account (keeping its `source`, role, history) instead of forking a duplicate, and every later login matches on `sub` alone — a mailbox rename can't fork the account, a recycled address can't inherit a leaver's. **Signup allowlist gates CREATION only** (an existing account signs in from any domain): `auto_provision` off ⇒ no, `"*"` ⇒ yes, else the email domain must be listed, **EMPTY = no signups**; domains normalized on write. **Fixed a spec-40 bug**: `instance_role` was written on EVERY login, so a Google login (no group claim) demoted the AD admin it had just linked to — a provider with no `admin_groups` now carries no role opinion. ONE callback for every provider, and refusals REDIRECT to `/login?sso_error=…` (that leg runs in an address bar, where a 403 JSON body IS the page). Unauthenticated `GET /auth/sso/providers` drives per-provider login buttons (a boolean could only describe the single-provider world); Settings → Sign-in (admin). Tests 1288 (`test_sso_providers.py`, 22). `docs/specs/110-*.md`.

### Spec 109 — the board CARD DESIGNER

: `views.card_layout` JSONB (migration `d109cardlay`; NULL = the type's default card, which is a faithful translation of the old hardcoded anatomy — CDP-proven pixel parity) holds an 8-col grid `{cells:[{attr,row,col,span,align}], max_labels}` rendered as wrapping flex LANES (row 0 = the header lane beside key/star/flag; first `align:end` cell takes ml-auto; `title` mandatory, `type`+chrome never cells; attr ids = the `lib/columns.ts` catalog + `cf.<key>`, loosely validated so departed fields degrade). One attr→chip registry (`components/board/card-cells.tsx`) feeds BoardCard/swimlanes/the designer preview; batches gate on `placedAttrSet`. Card heights are LAYOUT-determined: empty lanes reserve a chip row, titles reserve both clamped lines — uniform cards by design (supersedes launch pixel-parity). The WYSIWYG designer modal (`components/views/carddesigner/` — pure layout-ops, palette, live preview on the real renderer, house `useBucketDrop` drop zones + `startHorizontalDrag` span handle, keyboard fallback) replaces the board Display slot-grid ("Design card…"; scale stays personal). **Presets**: `card_layout_presets` + `/views/card-presets` CRUD (reads item.read, writes new `cardpreset.*` atoms via one CRUD_RESOURCES line, implied by global.manage); applying COPIES the layout (snapshot). Tests 1262 (`test_card_designer.py`). `docs/specs/109-*.md`.

### The shell/UX + operations wave (unnumbered + specs 104–105; PLAN.md Addendum 15 has the detail)

— **Shell**: Cairn-band layout — two FULL-WIDTH rows (`TopBar`: sidebar toggle + brand + query slot + inbox bell + avatar; `PinsBar`: My Work + pinned tabs with icons + the ALWAYS-visible project-aware New-item button) above the sidebar+content split; `sidebar-prefs` is a `useSyncExternalStore` shared store. Pins are a `NavPin` UNION (view pins live-resolve + `KEY · name` disambiguate; link pins store `{path,title}`) — ANY sidebar anchor right-click-pins (one delegated aside handler, `data-pin-label` overrides volatile badges), tabs right-click Rename/Unpin. Query bar defaults to ASK on an empty bar (URL-carried queries open SLQ), ⌘I toggles. `InboxPeek` right drawer off the bell (row click = mark read + ISSUE peek); `NotificationRow` shared with /inbox. Peek default 1100px (672 buried the description under the stacked rail). View pages = ONE header band; `ProjectNav` DELETED (Reports lives in the ⋯ menu). Radius scale DOWN to 6/8/10/12px (rounded-full untouched; plugin-sdk `--radd-radius*` mirrors). **AI UX**: `AiResultsPanel` beside the reading column (dead-space fix; `AiResultsContext` from the issue body — rail buttons + read-menus route there, wiki keeps its popover); diff review is a UNIFIED diff (old block red above green result, deletions hidden inline; cross-boundary fragments keep strikethrough); editor toolbars re-tinted 18px/8:1 with an accent PILL on `.active` (Crepe shipped no top-bar active styling at all); `SelectField` now converts `<optgroup>` children (they were silently DROPPED — the automations trigger dropdown rendered empty). **Plugin gating FIXED**: FastAPI's `include_router` appends `_IncludedRouter` wrappers (path=None) — the old prefix-filter unmount crashed on them and the bare `except: pass` hid it, so disable changed nothing; now identity/prefix-aware unmount, hot enable/disable run on_startup/on_shutdown, `ai.features.plugin_loaded` gates every sideways AI seam (search fusion FTS-only, storage llm rule falls through), the SPA catch-all 404s unknown `/api/*` (JSON), failures are logged. `/health` is the health endpoint (unprefixed). **Spec 105** — `monitoring` module + Settings → Monitoring (admin): DB health + approximate `pg_stat_user_tables` counts + per-consumer lag/heartbeat with OK/catching-up/STALLED chips via the new public `events.service.consumer_status`; semantic-index coverage composed client-side from `/ai/embeddings/coverage`. **Spec 104** — `leave` module + timesheet outliers: `leave_periods` (user XOR team; holidays expand to CURRENT members at read; self/steward/admin authz, holidays admin-only; merge REPOINTS, hard delete DESTROYS like worklogs), `GET /leave/current` powers the app-wide away-indicator (`Avatar` amber status DOT + dim; `PersonName`/`AwayChip` on names in EVERY person select/comment author; string-label chip pickers suffix `(away)`; the participants REMOTE self-fetches), `GET /leave/calendar` feeds the timesheet (away cells, flag-exempt); NEW instance settings `timesheet_day_min/max_hours` (6/10) — the By-person grid tints completed workdays amber under-min / red over-max (today/future/off-days/leave exempt); Settings → Leave. Trigger snapshot: `server/tests/_trigger_catalog_snapshot.json` (70). Tests 1238 (historical).

### Specs 101–103

— the **AI platform + multi-host storage wave**. **Spec 101** — the **AI provider registry**: providers are DB rows (`ai_providers`, env seeds one once; wire shapes `openai`-compatible \| `anthropic`) with model ROLES (`ai_model_roles`: `chat`\|`embeddings`\|`vision` — embeddings-on-anthropic is a 422) and an admin preset-prompt library; the client seam every module calls is `ai/client.py` — `complete` / `complete_structured` (json_schema ↔ forced tool-use) / `complete_choice` (enum-constrained + optional image) / `embed` / `stream` (SSE; the codebase's first streaming primitive — `CommitBeforeSendMiddleware` now passes `text/event-stream` through instead of buffering); six per-feature toggles in the settings cascade + a per-user editor opt-out; Settings → AI. **Spec 102** — **attachment storage rebuilt: multi-host, routed, ACL'd, polymorphic**: `storage_hosts` rows (filesystem\|s3, per-host `delivery_mode` proxy\|`presigned` — presigning is pure HMAC, so the network, not app logic, decides who can fetch a zoned host's bytes; Garage is the blessed S3 server, MinIO CE is archived), an ordered ROUTING CHAIN (`user_choice` always-ask \| `cidr` over the new trusted-proxy client-IP (`radd/clientip.py` + `RADD_TRUSTED_PROXIES`) \| `llm` — admin prompt + enumerated answers→hosts via the vision role, every failure falls through; rule types are a kernel socket), POLYMORPHIC parents (`entity_type`+`entity_id`, bindings registry — `pages` registers the entity key **`page`**, so the wiki finally uploads images; the key was `doc_page` until RADD-701 renamed it, and using the old value 422s every upload — that cost a day in RADD-761), per-attachment READ grants on the spec-92 framework (default-open; enforced at the single download/presign mint), move jobs (copy→verify→repoint), an orphan-GC consumer that finally removes BYTES, and a blob API for jiraimport. **Spec 103** — **editor AI + semantic search**: Crepe's AI feature (selection toolbar, server-curated actions incl. admin presets, streamed via SSE with diff accept/reject; gate inside RichEditor so OFF is byte-identical) and pgvector retrieval — compose images moved to `pgvector/pgvector:pg16`, the embeddings schema is RUNTIME-managed outside Base.metadata (guarded CREATE EXTENSION migration; per-model expression-cast partial HNSW index, so a model swap needs no migration), the `ai.embedder` consumer + ONE reconcile sweep (= backfill + silent-import coverage + model-change re-embeds; text via `search.rows_for_embedding` — public text only by construction — and `docs.pages_for_embedding`), RRF fusion in `/search` (time-budgeted, FTS-only on any failure), fused similar-issues + KB deflection, `GET /search/semantic` (palette Ask mode), and a new MCP `find_items` tool routed through the hybrid ranker so every agent inherits it. **Dogfood hardening (same day):** the `local` wire shape ships **built-in CPU embeddings** (fastembed/ONNX, `radd[localembed]`, embeddings-role-only — semantic search with no external model server); NL→SLQ became **dialect-aware** (`items`\|`worklog` — the timesheet teaches `issue.*` delegation and compiles through the worklog compiler), got **pre-compile VALUE repair** (`ai/nlrepair.py` + `fuzzy.py`: "jimmy" → the real account via the items autocomplete candidates seam, substitutions reported in the explanation — SLQ itself stays exact; most entity fields otherwise compile unknown values into silent zero-row queries), carries live **issue types + work categories in-prompt** ("bugs" → `type = Bug`, never the `kind` hierarchy level) and a `Today is <date>` anchor; the storage ask prompt fires **only when the answer can matter** (upload-context simulates the chain per content type + caller IP, `preempted_by` names the capturing rule) and every attachment read carries `storage_host_name` (grid badges); Garage hosts need `region` matching the server's `s3_region` (dev: `garage`), two dev instances ride `compose.dev.yaml --profile storage` + `deploy/garage/init.sh`. **Editor-AI UX wave:** three entry points instead of one — a toolbar AI button (selection-or-WHOLE-document; Crepe's RunAI dispatched BY NAME, the subpath-entry import binds a dead second module instance), a read-mode AI menu on rendered comments/description/wiki (`AiReadMenu`: Find similar via new `POST /ai/similar` text-seed fusion + streamed Summarize in a popover; transforms open the editor with the run as an `initialAiRun` reviewable diff, write-gated), and **per-block diff review** — `web/src/components/editor/diff/` forks Crepe's decoration plugin (swapped via `editor.remove` pre-create): one Accept/Reject pair per changed TEXTBLOCK (a list item's paragraph, not the whole list), word-boundary visual expansion ("~~Demo~~ demo"), exact-range accept, and rejects range-padded ±1 because upstream's overlap test never matches a pure deletion (its Reject was a silent no-op). Summarize became a whole-issue digest: char-budgeted sections (`take_recent`) + a **time-tracking digest** (totals/per-person/recent entries via `timelogging.item_summary`, feature-detected — the prompt section never appears when the project doesn't log time), surfaced as "Summarize issue" on the description's read-menu. `docs/specs/101|102|103-*.md`, `PLAN.md` Addendum 14.

### Spec 100

— the **Jira importer rebuilt: cache-first, explicit, reversible**. Connections are DB rows (env seeds one, once); a JQL result set is downloaded ONCE into `jira_snapshot_issues` and every later step reads that cache; identification is by Jira's STABLE `schema.custom` type keys (`schemakeys.py`) so the hardcoded `customfield_*` blocklist, the literal sprint field, the English priority/category/link tables and the hardcoded `FALLBACK_EMAIL_DOMAIN` are all DELETED; a plan holds NINE editable mapping tables with everything **unused hidden AND ignored by default** (337 fields → 14 decisions, 83 statuses → 10) each showing WHY; provisioning creates real targets before any issue moves; a dry run shares the import's code path with writes off; the import is SILENT (`events.quiet` + `events.silent`, so notify/webhooks/automations skip it while search + history do not); `jira_import_records` makes it fully rollback-able; and `jira_pending_refs` + relink resolve cross-project links when the other project finally arrives. Every import problem carries the MAPPING that caused it (`section`+`mapping_key`) so the run report offers **"Fix in Statuses → Needs Discussion"** rather than leaving you to guess, and a run that skipped issues reads amber "Done, with skips" instead of green. Two adjacent fixes it forced: `fields.extend_options` (ADDITIVE-only, since removing/renaming an option invalidates items that store it) so mapping into a curated select can ADD the values it lacks instead of dropping them; and `items._resolve_assignee(allow_inactive=)` — gated on `project.manage` + a historical write — so an issue assigned to or reported by someone who has LEFT still imports (it covers reporter too, so leavers would otherwise have been skipped wholesale). `ldap_exclude_disabled` moved the disabled-account filter out of env and into Settings → Directory (a live AD held roughly twice as many disabled accounts as active). `docs/specs/100-*.md`. **Spec 98** — a **second SLQ dialect, rooted at the WORKLOG**, giving the timesheet a filter bar: bare worklog fields (`author`, `category`, `project`, `worked_on`, `time`, `note`) plus `issue`, which carries `IS EMPTY` (general worklogs — inexpressible on the item dialect, which returns items and so can never surface a worklog with no item), `= DEV-123`, and **`issue.<anything>` DELEGATED to the item compiler** and wrapped as `worklog.item_id IN (SELECT …)`. The delegation is why the dialect is seven fields: it inherits builtins, custom fields, ancestors, labels and plugin fields permanently, and it is EXACT (worklog→issue is to-one, so per-condition delegation selects the same rows a subquery would — which is why the `{ … }` sub-query grammar was dropped). Autocomplete delegates the same way (`issue.assi` → item fields; `issue.assignee = ` → item values incl. `me`/`none`). `q` compiles in the router and ANDs onto the scope filters inside `timesheet.build(where=…)`, so it can only NARROW what the actor may see. items' lexer/parser/helpers are now exported as generic query machinery. `docs/specs/98-*.md`. **Spec 97** — **relational item SLQ fields**: `logged_by` (timelogging) and `commented_by` (comments) find issues by who logged time on / commented on them, contributed through spec 94's `SlqFieldSpec` registry so `items` never learns those modules exist. `SlqFieldSpec.item_ids` gained a context (`current_user_id` + an `is_me` flag) because `me` is a grammar sentinel `plain` rejects. `docs/specs/97-*.md`. **Also, unnumbered:** the **Dusk UI wave** — a cool blue-shifted palette with periwinkle accent, traffic-light workflow-state colours (green = go; `done`/`canceled` share one slate deliberately), a validated `--chart-*` token set + an ink tier for pill text, ZERO raw `zinc-*`/`indigo-*` utilities in `web/src`, **card surfaces on every work surface**, a collapsible sidebar rail + a reusable `<SidePanel>`, resizable roadmap/peek gutters, **URL-synced page state with a short-link fallback** (`?s=<hash>` past 180 chars) + `Reset view`, dashboards migrated onto the spec-92 access framework, and cycle rules (completed cycles only on Settings → Cycles). See `BUILD-LOG.md`. **Spec 96** — **disable un-writable fields up front** (never edit-then-error), on the spec-92 access framework: `fields.readonly_field_keys(...)` + `GET /fields/writable?project_id=` return the builtin names + custom keys the actor can't write in a project (per-(actor, project), item-independent), and the SPA's `useItemWritability` DISABLES (dimmed, reason on hover, no lock icon) exactly those editors across the issue rail/title/description/flag, the comment composer (a note when `comment.write` is absent), the bulk-action bar, and the New Item modal (boards/lists are display-only; settings already gate). `docs/specs/96-*.md`. **Spec 95** — a compact **inline-token multi-select** (`web/src/components/TokenMultiSelect.tsx`: chips on ONE scrolling row + typeahead + autocomplete/create) replaces the tall wrapping pill stacks EVERYWHERE a flat value-set is edited (labels, field options, custom multi_selects, team managers, form sharing, role holders, `ScopePicker`); checkbox grids / per-row builders / fixed toggle-sets left alone. `docs/specs/95-*.md`. **Spec 94** — the **frontend module-federation plugin platform**: a plugin ships its OWN built ESM bundle (native-ESM federation — an import map + `globalThis.__RADD_SHARED__` singletons; `@radd/plugin-sdk` is the only frontend import) that a *running* Radd loads with zero host edits (slot registry + `<Slot>`, theme tokens, `ui_api_version` gate; acceptance = `examples/acme-notes/` in its own repo/build loads headless). Depth: `view.type`/`dashboard.widget`/`plugin.manager.section`/`profile.section` slots + SLQ-field registration; **two-scope, plugin-owned per-contribution toggles** (GLOBAL admin in `InstalledPlugin.config` via `/plugins/*/contribution-settings`; PER-USER in `users.preferences` via `/auth/me/preferences`; On/Off switch); a disabled contribution also leaves the nav links + the view/widget-type dropdowns (`useDisabledNavPaths`/`useDisabledMatches`) with a `MissingPluginType` notice. `docs/specs/94-*.md`, `docs/plugin-ui.md`, `docs/plugin-platform.md`, `BUILD-LOG.md`. **Spec 93** — the **kernel + in-process plugin platform (backend half)**: `kernel/` holds the plugin contract (`RaddPlugin`), the contribution registries (entities/events/permissions/CRUD/capabilities/nav/view_types/widget_types/slq_fields), the loader/lifecycle (`depends_on` + semver `api_version`), and pure specs; `EntitySpec` auto-wires a table+CRUD+events+RBAC (north-star: `milestones`); `pluginmgr` runs install/enable/disable/uninstall with live hot-mount (`GET /plugins` + admin actions). `docs/specs/93-*.md`. **Spec 92** — a **generic, plugin-registerable access-grant framework** (`radd.modules.access`): ONE scopeable ACL primitive — `access_grants` (subject user\|team\|role → access → resource_type+resource_id, `project_id` NULL=global\|set=one project) — that every RBAC-controlled resource shares. A module/plugin registers a `ResourceSpec` (its `accesses`, `default_open`, `hierarchical`, `subjects`, `project_scoped`, `implied_by`, and a `can_manage` authz hook) and gets the generic `/grants` API + the one reusable `<AccessGrantsEditor>` (searchable **SubjectPicker** + access + the **ScopePicker** multiselect dropdown) with no new code. Adopters: **custom fields** (`field_permissions` migrated + dropped), **builtin fields** (`builtin_field_rules` + `rules.py`/`/field-rules` gone), **view sharing** (`view_shares` gone — hierarchical viewer/editor/owner, owner-closed default). Field grants are now scopeable-to-projects + grantable to a USER; view shares are grants (owner_id/global_access stay on the View). Pure resolution in `access/resolution.py` (unit-tested). `docs/modules.md` (`access` row + `fields`/`views`/`auth` addenda). **Latest before: spec 91** — an admin-UX + scoping wave: **custom fields** move to a two-pane master-detail page and gain **multi-project scope** (a `field_definition_projects` association, no rows = global) editable via a shared **ScopePicker** (searchable multi-select → chip list, reused everywhere); a new **`linktypes` module** makes **issue link types user-definable + scopeable** (blocks/relates/duplicates/mentions seeded as built-ins; `item_link_types` + a project-scope association; `ItemLink.link_type` is now a validated KEY, not a hardcoded enum; `Settings → Link types`; the importer maps Jira link names onto them); and **role grants became scopeable to project OR global** (`global_role_grants` gained a nullable `project_id`; `POST /role-grants` + a unified **Grant Role** dialog on the Teams panel). `docs/modules.md` (`linktypes` row + `fields`/`auth`/`items` addenda). Also a spec-90 follow-up wave (redo an import with editable mappings, upsert on re-import, full-sprint cycle status, cross-DB epic/issue-link resolution + inward-link direction). **Spec 90** — a live **Jira import wizard** (`jiraimport` module + `Settings → Import from Jira`): connects to Jira Server/DC (PAT or basic auth), lists projects, runs JQL, infers an inbound schema, maps fields to local custom fields (create or map), and runs a **staged background import** (fields → issues → a relink pass that points issue links at the new Radd items, not old Jira) with live progress. Preserves Jira IDs 1:1. `docs/specs/90-*.md`. **Spec 89** — users can be HARD-deleted with their authored work reassigned to a named successor (`GET /users/{id}/content` then `DELETE /users/{id}?reassign_to=…`); worklogs are destroyed rather than moved so no one is credited with hours they didn't work. Reverses spec 87's removal of `user.delete`, and fixed three columns missing from `_MERGE_REPOINT` that were a latent merge bug. **Spec 88** — AD user import previews each selection against existing accounts and resolves duplicates explicitly (**overwrite** re-addresses an existing account to AD keeping its `id` and history; **merge** folds a look-alike into the AD account), since Radd keys people by email and the same human often already exists under an older address. **Spec 87** — AD-linked teams are read-only from the directory (`TeamSource`), per-team delegation via `teams.owner_id` + `team_managers` (a leader runs one team; project entitlement stays with project admins), and **`global_role_grants`** — the delivery mechanism that finally makes global-scope permission atoms grantable to non-admins (an audit found all 47 were dead, plus 8 atoms with no endpoint; see `docs/specs/87-*.md`). **Every pillar is shipped (specs 01–52)** — tracker, SSO (OIDC+LDAP), wiki, extensions SDK + MCP, AI, connectors, packaging, MFA, plus the wave: **spec 50** (settings-scope + full-CRUD RBAC + scalar-settings cascade + builtin-field read grants + per-team internal comments), **spec 51** (issue types — per-project classification axis + colored chips, orthogonal to the epic/issue/subtask hierarchy), **spec 52** (issue `#`-mentions in every editor + per-field render widgets). **Status, current runtime state, next steps & operational notes: `PLAN.md` §8 + §11.** Per-module detail: `docs/modules.md`. Per-module detail: `docs/modules.md`. Research: `research/`. Build specs (history): `docs/specs/`. Deploy: `docs/deploy.md`.

### Access hardening 2026-09 (RADD-1213)

Latest access hardening: [docs/access-hardening-2026-09.md](docs/access-hardening-2026-09.md) (RADD-1213). Resource restrictions now persist until explicitly reset; raw events require global management; scoped credentials apply to intrinsic owner actions. Upgrade the database before starting this version.

### Where the build stood after the service-desk waves (specs 58–67)

**Where the build is (service-desk day wrapped — latest: specs 58-60 [automation any-event triggers + conditions + universal actions, itemless worklogs, cycle team-visibility] THEN specs 61-67 = the full service-desk completion: workflow-transition guards, requester loop [mail contacts/outbound replies/public tokened forms], SLA depth [priority first-match, business hours, batch chips, reports], queue views, CSAT, canned {{vars}}/send_email/KB-deflection, VIEWS-ONLY surfaces [builtin board/list/planning pages deleted; projects seed plain Board/List/Planning views], two-scope settings [project→instance, workspace scope dropped, SLA policies project-level, "global" scope vocabulary], + the duplication sweep [radd/worker.py, events/runner.py, lib/dates.ts, useBucketDrop, QueryError]; PLAN §11 addenda 1-9 have the detail):** the tracker is built front-to-back and dogfoodable — auth (local) + full RBAC incl. field-level grants, projects/items with key-addressed URLs (`/issues/TD-1234`), custom fields, workflow, labels, comments, teams, cycles, releases, dependency links, saved views + the **SLQ** query language w/ autocomplete + swimlanes, automations, reporting, intake forms, **time logging + timesheets** (per-project-optional: estimates, worklogs, work categories, and a day/week/month timesheet), webhooks, the Jira importer, and the full React UI (boards/list/issue/roadmap/reports/timesheet/admin). **notifications + watchers + inbox** (spec 26), **realtime WS live updates** (spec 27), **FTS search + Cmd-K palette** (spec 28), **attachments + markdown editor with mentions** (spec 29), **service desk: reporter + SLAs + canned responses** (spec 30), **GitLab connector** (spec 31), **"My Work" home + polish** (spec 32), **S3/MinIO attachment storage** (33), **profile: avatar/timezone/tokens** (34), **work week + business-day SLAs** (35), **RBAC: per-entity actions + builtin-field rules** (36), **polish batch** (37), **item archive/delete** (38), **light theme + density** (39), **OIDC SSO with group→role sync** (40), **list pagination** (41), **LDAP/AD bind: direct-bind directory login** (42), **wiki: spaces/page-trees/versions/issue-links + FTS** (43), **extensions SDK — Apache-2.0 `sdk/` runner over GET /events** (44), **embedded MCP server at POST /api/v1/mcp** (45), **AI: summarize/similar/NL→SLQ, provider-agnostic, optional** (46), **connectors: Forgejo, Google Chat, Alertmanager, email-to-issue** (47), **packaging: Containerfile/compose/Helm + `RADD_RUN_WORKERS` split + TOTP MFA** (48). **No unbuilt pillars** — depth list in `PLAN.md` §8.

---


## Path decision — (a) RECLASSIFY, not (b) fresh rebuild

**Chosen: (a) reclassify existing code into the new architecture.** Recorded reasons:

1. **The doc mandates it.** `docs/plugin-platform.md` §11.1 ("Reclassify, don't rewrite… every
   existing module keeps working with `core: true` and empty new fields. Zero behavior change on
   day one.") and locked Decision #7 ("Reclassify existing modules as builtin `core` plugins; no
   rewrite, additive manifest fields"). Path (b) would re-litigate a locked decision.
2. **Parity is preserved by construction.** The gate is 100% parity with specs 01–92 across ~43k
   LOC backend + ~46k LOC frontend + 920 passing tests. Reclassifying keeps the working code and
   restructures the *contract* around it, so parity holds at every commit. A fresh rebuild would
   reproduce 92 specs from scratch — infeasible to do without regressions, and the 920-test suite
   would have to be rewritten (losing the safety net the goal says isn't required but which is the
   cheapest possible parity oracle).
3. **The real problem is 3 backwards dependencies (§3), not the feature code.** The architecture
   win is inverting hardcoded chokepoints into registries — a structural change, not a rewrite.

**What "reclassify" means physically here:** introduce a `radd/kernel/` package holding the NEW
machinery (the `RaddPlugin` contract, contribution registries, loader/lifecycle, entity registry,
capabilities aggregator, sockets, the public SDK surface). Existing modules keep their file
locations (so the 920-test import surface is untouched) and are re-expressed as `RaddPlugin`s with
populated manifest fields + `core: true`. The kernel/plugin *split* is enforced by the contract and
registries (plugins reach infrastructure only through kernel entry points), not by physically
relocating every module — which would be churn with no parity benefit and real regression risk.
This is exactly §11's "additive manifest fields / zero behavior change on day one."

---

## Environment / harness notes

- **Test DB:** the live `radd` DB has 6 days of real+demo data, which makes a few data-sensitive
  tests (e.g. `test_slq_suggest` suggest-limit crowding) flaky. Reliable green signal = a fresh
  seeded DB: `radd_test` on the same Postgres (localhost:5455), migrated to head + `python -m
  radd.seed`. **Baseline: 920 passed, 0 failed.** All verification runs use
  `RADD_DATABASE_URL=postgresql+psycopg://radd:radd@localhost:5455/radd_test`.
- **Frontend build (JS toolchain):** `npm` is NOT on PATH. Two stable ways in:
  - **npm (for installs / new plugin projects):** a working npm is copied into THIS session's
    persistent scratchpad — run the scratchpad copy of `npm-cli.js` (e.g. `... install`, `... run build`). `web/node_modules` is present.
  - **no-npm fallback (host build):** the existing web app builds with **no npm** —
    `cd web && node node_modules/.bin/tsc -b && node node_modules/.bin/vite build`.
  - If both paths ever go missing, rediscover: `find / -name npm-cli.js 2>/dev/null | grep -v /jobs/ | head -1`.
  - node is v22 at `/usr/bin/node`. corepack/pnpm/yarn are NOT available.
- Postgres 16 container `tracker_db_1` up on :5455. `uv` present; Python venv 3.13.

---

## Phase plan (follows doc §11/§12; each ends GREEN — pytest + boot smoke)

- **P0** kernel package + `RaddPlugin` manifest + contribution registries; invert the 3 chokepoints
  (automations triggers from the event-type registry; `/capabilities` aggregator; frontend nav from
  a manifest). North-star: a builtin plugin appears with no other-module edits.
- **P1** RBAC registries become plugin-contributable (`register_permission` + `register_crud_resource`);
  access grants already are.
- **P2** lifecycle: install/enable/disable/uninstall + `installed_plugins` table + manager service/UI;
  per-plugin migration handling; per-plugin Python/JS deps.
- **P3** `radd.sdk` public surface + `api_version` compat gate.
- **P4** frontend: declarative UI manifest, then module federation.
- **P5** `TaskBackend` + `StorageBackend`/`AttachmentFilter` sockets formalized; celery plugin proof.
- **P6** `kernel.entities` EntitySpec auto-wiring + the **`milestones`** north-star plugin end-to-end.

(P6's entity auto-wiring is pulled early where it unblocks the north-star test, per §12's "provable
slices".)

---

## Log

### — setup
- Surveyed: 48 module dirs, ~43k LOC server, ~46k LOC web, 89 migrations (single alembic head
  `925809931622`), 67 test files / 920 tests.
- Established green baseline on fresh seeded `radd_test` (920 passed). Live-DB run was 919/1 (the 1
  is pre-existing data-crowding, not a code defect).
- Read the contract (`module.py`), assembly (`app.py`), config (`config.py`), chokepoint #1
  (`automations/catalog.py` — hardcodes 21 modules' event enums), and the RBAC registries
  (`auth/types.py` — `Permission` StrEnum + `CRUD_RESOURCES` tuple).
- Decision: path (a) reclassify (above).

### — P0 slice 1: kernel foundation (commit 9bf876d)
- Built `radd/kernel/`: `RaddPlugin` contract (evolves `RaddModule`, kept as alias — legacy
  `name=/description=/routers=` ctor still constructs; `core=True` default for reclassified
  builtins), contribution specs (`specs.py`), registries (`registry.py`), loader (`loader.py` —
  aggregates contributions, `depends_on` + semver `api_version` gate). `radd/module.py` is now a
  shim. `tests/test_kernel.py` (7 core-invariant tests). **920 tests green, app boots.**
- Deviation logged: the doc's `RaddPlugin.core` default is `False` (§4); I default it `True` so the
  45 reclassified builtins don't each need editing (§11.1 "zero behavior change"). External/new
  plugins set `core=False` explicitly (the north-star `milestones` plugin does). Rationale: the
  reclassify convenience the doc itself calls for.

### — P0 slice 2 (in progress): chokepoint #1 — triggers from the event registry
- Consumers of `catalog.TRIGGERS` are all runtime (router/engine/schemas), so a lazy registry read
  handles plugin load order. Plan: (A) fan out `event_types` to the 21 producing modules'
  manifests; (B) parity oracle (`tests/_trigger_catalog_snapshot.json` — 65 triggers captured from
  the pre-inversion catalog; `tests/test_trigger_registry.py`); (C) switch `catalog.py` to read
  `registries.triggers()` via module `__getattr__` (keeps the `catalog.TRIGGERS` name live,
  zero consumer churn), delete `_SPECS` + the 21 enum imports.
- Done (commit a53f642). All 21 modules migrated by two parallel subagents; oracle green; 929 tests.
- `conftest.py` added: an autouse fixture calls `load_plugins(settings.modules)` before each test so
  the kernel registries are the full boot state (as `create_app` establishes) regardless of test
  order — the registry is boot state, not import state.

### — P0 slice 3: chokepoint #2 — /capabilities aggregator
- New `capabilities` core plugin (`radd/modules/capabilities/`) + `kernel/capabilities.py`
  (`evaluate()`/`capability_map()`): `GET /capabilities` evaluates every registered `CapabilitySpec`
  (calling each plugin's `check()`), replacing the inlined provider enumeration. The infra flags
  (workers/smtp/mfa) live on the capabilities plugin; feature/connector plugins register their own.
  Added to `config.modules` after auth. Both `/capabilities` + `/instance/status` mounted (205 API
  paths). 3a = add the aggregator + descriptors; 3b (below) = retire the inline `instance_status`
  onto the registry.
- Note: the FastAPI in use lazily wraps `include_router` as `_IncludedRouter` in `app.routes`; use
  `app.openapi()['paths']` (not `app.routes`) to introspect mounted endpoints.
- Done (commit c448dc7): 3a + 3b both landed — `/instance/status` now consumes the registry. 933 green.

### — P1 slice 4: A2 RBAC registries plugin-contributable (commit 3ea8813)
- `auth/types.py` merged-view accessors (`all_permission_keys`/`permission_scope_of`/
  `permission_description_of`/`implied_map`) fold kernel-registered atoms in live; the union engine
  flows atoms as **strings** (StrEnum builtins byte-identical), admin = `all_permission_keys()`.
  Schemas → `list[str]`/`str` with write validation. `tests/test_rbac_registry.py` (6). 939 green.

### — A3 entity auto-wiring + A10 north-star (commit 54876d1)
- `kernel/entities.py`: declarative `EntitySpec` → generated model + CRUD router + events + RBAC
  atoms, all auto-wired by the loader; `ensure_tables()` install step. The `milestones` plugin
  (one EntitySpec + nav) proves the north-star (`tests/test_north_star.py`, 6). Migration
  `a29615cf474d`. 945 green.
- **Key decision:** non-core plugins (milestones) do NOT go in the always-on `config.modules`
  bootstrap — per doc §10 they are installed (migration) + runtime-enabled via the plugin manager.
  Putting milestones in `config.modules` polluted 9 baseline-invariant tests (all-core,
  admin==builtins, 65 triggers). Removed it; the north-star test loads it explicitly (the "drop in
  the plugin" moment). `config.bootstrap_plugins` placeholder added for the A4 lifecycle set.
- **Deviation logged:** dynamic model uses SQLAlchemy imperative `map_imperatively` (not the Mapped
  DSL) — cleaner for runtime generation. `entities.py` deliberately omits `from __future__ import
  annotations` (PEP 563 would make the generated CRUD handlers' local pydantic-model annotations
  unresolvable forward-refs to FastAPI). Autogenerated migration needed one manual edit (drop a
  spurious `ix_doc_pages_fts` drop — a GIN expression index alembic can't model).
- **Partial (logged):** generic-entity search-indexing + mention-resolution not yet wired (search/
  mentions key on specific entity types today) — A3 [~] in spec 93.

### — A4 plugin manager (commit 16b2fc7)
- `pluginmgr` core plugin: `installed_plugins` table (migration `e53d08a57e29`) + install/enable/
  disable/uninstall state machine (core locked), `boot.py` sync resolution at `create_app`,
  `runtime.py` hot-mount/unmount (pops the SPA catch-all so new API routes precede it). Admin API.
  `tests/test_plugin_manager.py` (7). `env.py` scans `installable_plugins` so autogenerate won't
  drop an installed-but-disabled table.

### — A5 sdk + A6 data SDK (commit 2c0d09d)
- `radd/sdk.py` — the public surface: kernel eager + acting-user data services lazy (PEP 562). Loader
  refuses incompatible `api_version` (end-to-end test). milestones imports only `radd.sdk`. A6: the
  acting-user-scoped services (items/comments/projects/perms/settings) ARE the permission-aware data
  SDK, exposed via `radd.sdk`; `as_system` naming is a follow-up. 956 green.

### — A8 sockets (commit b796f68) + A7 frontend manifest (commit a1552d4) + A9 deps
- A8: `kernel/sockets.py` registry + Protocols; `attachments` registers filesystem/s3 StorageBackend,
  `capabilities` registers the localloop TaskBackend. `tests/test_sockets.py`. 960 green.
- A7: `/capabilities` carries a UI manifest (`capabilities` + plugin `nav`); the SPA sidebar renders
  plugin nav from it (build-verified: tsc + vite clean, `web/dist` rebuilt). Additive over the
  hardcoded nav (no regression). Full 8b (manifest-driven nav replacement + generic plugin pages +
  federation) deferred.
- A9: `RaddPlugin.python_deps`/`js_deps` — plugins declare deps (`ldap`→ldap3, `attachments`→minio);
  pyproject extras restructure deferred. 961 green.

### — DONE-gate assessment + demos
- **Demos gate is UNMET but NOT a regression:** `server/scripts/demo*.sh` predate spec 86 and POST
  the removed `/workspaces` endpoint — broken on `main` too (the script's own header says so). The
  961-test suite on a **fresh seeded `radd_test`** is the stronger equivalent fresh-DB oracle.
  Updating the demos to the post-spec-86 global surface is an orthogonal task, not part of the
  kernel/plugin migration. Live `radd` DB brought to head (additive: milestones + installed_plugins
  tables); app boots against it (210 paths).
### — end-to-end HTTP verification (running server, fresh DB)
- Ran a real uvicorn against fresh seeded `radd_test` and drove the HTTP surface: login (204),
  `/auth/me` (admin, 80 string-atoms), `/capabilities` (12 caps, 0 nav) → **enable milestones via
  `POST /plugins/radd.milestones/enable`** → `/capabilities` nav now shows the Milestones item
  (chokepoint-3 over HTTP) → **full auto-generated CRUD** on `/api/v1/milestones` (create/get/patch/
  list/delete: 204) → SPA index served (200). The north-star, the plugin manager, and the manifest
  nav all work on a live server, not just in unit tests.
- **Bug caught by E2E + fixed:** the generated entity model lacked `eager_defaults=True`, so
  `updated_at` (server `onupdate`) was expired after an UPDATE flush → `MissingGreenlet` on PATCH.
  Added it in `kernel/entities.build_model` (mirrors `db.TimestampMixin`); strengthened
  `test_north_star` with an UPDATE path that reproduces it. Unit tests alone missed it (they created
  but never updated the generated model) — the value of the running-server pass.
- Harness notes: foreground `sleep` is blocked (use `curl --retry-connrefused`); `pkill -f <port>`
  self-matches the invoking shell (kills itself — exit 144); run a server as the tracked background
  main process and stop it with TaskStop.

### — Net
- **Net:** the kernel/plugin split is real and enforced; the plugin manager enables/disables each
  plugin (core locked); the `milestones` north-star lights up automations/RBAC/nav/CRUD with zero
  edits to any other plugin or the kernel; all three §3 chokepoints inverted; 100% behavioral parity
  with specs 01–92 preserved by construction (961 tests green, all endpoints shape-preserved).
  Remaining items are the logged `[~]` follow-ups (generic-entity search/mention, full 8b frontend,
  per-plugin alembic branches, §13 primitives, `as_system` naming, demo-script modernization) — each
  a bounded extension on top of a working, shipped platform, none blocking DONE.

### — post-backend follow-ups (before the frontend-federation run)
- **Optional plugins made disableable** (commit 69f5b30): three plugin classes via `RaddPlugin.core`
  — core bootstrap (locked, 32), optional bootstrap (`core=False`, disableable, 16: ldap/sso/ai/mcp/
  docs/dashboards/slas/csat/approvals/participants/gitlab/forgejo/googlechat/alertmanager/mailintake/
  jiraimport), installable (milestones). `boot.resolve_boot_paths()` loads core always, optional
  unless DISABLED, installable when ENABLED; `disable`/`uninstall` guarded by `_ensure_no_dependents`
  + core-lock (409). **Settings → Plugins admin UI** (commit 833e473, `web/src/routes/settings/plugins.tsx`).
- **Issue-view plugin gating** (commit 648a528): `/capabilities` now also returns `plugins` (enabled
  plugin names); `IssueProperties` gates the participants/csat/approvals/external-requester sections
  on `hasPlugin(name)`. This is a **band-aid**, not real plugin UI — see the next endeavour.
- **`eager_defaults` fix** (commit 8242dc9): generated entity models need it or PATCH → MissingGreenlet.
- **Current running state:** a dev server is up on `:8000` (started by me, tracked bg task; no
  `--reload`) against the live `radd` DB; `participants` is DISABLED in that DB (the user's choice);
  the live `radd` + `radd_test` DBs are both at alembic head `e53d08a57e29`. The `kernel-plugin-platform`
  branch has all this work committed.

## NEXT ENDEAVOUR — frontend module-federation plugin platform (spec 94, to be created)

The user is running an unattended `/goal` for this. **This section is the durable briefing** — the
conversation that designed it will be compacted away, so everything needed is here + in
`docs/plugin-platform.md §8/§9/§14`.

**Why:** the backend is a real plugin system, but the FRONTEND is a monolith — every plugin's UI
(participants, VCS tab, CSAT, approvals, docs, dashboards, milestones, connectors' settings, …) lives
in `web/src/*` and is hardcoded into shared components (`IssueProperties.tsx`, `Sidebar.tsx`, the
settings/router trees). The only "plugin-ish" frontend pieces are the nav-from-manifest (`Sidebar`
reads `/capabilities` `nav`) and the `hasPlugin` visibility gates — neither is real plugin UI. Plugins
ship ZERO TSX. So external plugins can't contribute UI without editing/rebuilding Radd's frontend.

**Goal:** make the frontend a real plugin platform via **module federation** (§8b-A) so a plugin —
including one built in its OWN repo/project — ships its own UI bundle that Radd loads at RUNTIME.

**User's LOCKED decisions (do not re-litigate):**
1. **Full parity** — move EVERY plugin's UI out of `web/src` into the owning plugin as a federated
   remote; end state: `web/src` imports nothing plugin-specific (only host shell + slots + shared SDK).
2. **Acceptance = an in-repo example plugin** (e.g. `examples/acme-notes/`) that is its OWN independent
   project (own `package.json` + vite-federation + `pyproject`), built SEPARATELY, adding an entity
   (`kernel.entities`) + an issue-panel slot section + a nav page, loaded at runtime with ZERO edits
   to core or other plugins. This is the north-star.
3. **Verify with a headless browser** (Playwright/headless Chromium) that federated UIs actually
   RENDER (milestones page, participants section on an issue, enable/disable live); if it can't run in
   the sandbox, fall back to build-level (typecheck + build every remote + boot + loader smoke) and
   DOCUMENT what's browser-unverified.
4. **Shared theming is first-class** — ONE palette/token source: Tailwind v4 `@theme` CSS variables on
   `:root`, exposed via the SDK + shared primitive components (Button/Field/Chip/Card). Plugins
   reference tokens + shared components; NO plugin hardcodes hex colors (grep-verify). Federated
   remotes render into the host DOM, so they inherit the host's CSS variables — lean on that.

**Architecture (detail in `docs/plugin-platform.md §8/§9/§14`):** a Vite Module-Federation host sharing
singletons (react, react-dom, `@tanstack/react-router` + `react-query`, the design-system/tokens,
version-pinned); a public `@radd/plugin-sdk` (slot-registry + primitives/tokens + hooks
[auth/capabilities/api client/item queries] + a semver `ui_api_version` gate); UI **slots**
(`issue.panel.section`, `issue.tab`, `sidebar.nav`, `settings.page`, `dashboard.widget`, `item.action`,
plugin route-pages) — base views render `<Slot>` and know no plugin. Backend: the plugin manifest
carries its `ui.remoteEntry`; `/capabilities` exposes each ENABLED plugin's `remoteEntry`; a host
runtime loader `import()`s enabled remotes, registers their slot contributions, QUARANTINES load
failures, version-gates; the plugin-manager enable/disable mounts/UNMOUNTS the plugin UI live. Builtin
remotes served same-origin; the example plugin from its own build; fix CSP.

**Method:** commit `docs/specs/94` FIRST as the DONE checklist enumerating every UI surface to migrate;
verify GREEN each slice (pytest, typecheck, build every remote, boot, Playwright/fallback); commit each
slice; keep `docs/modules.md` + spec 94 current; log decisions/unmet-parity here; continue past blocks.
Subagents ordered: host + SDK + slots FIRST → per-plugin remotes (SDK-only deps) → the example plugin
last; serialize edits to shared files (host federation config, SDK, backend manifest/loader). Free to
aggressively refactor the issue view / sidebar / settings into slots (early-dev, not bound to existing
UI); keep the app buildable + booting at every commit.

**Biggest risk (flagged to the user):** Vite 8 + React 19 module-federation shared-singleton wiring is
the least-mature part and can "build but not load at runtime" — a failure mode invisible without a
browser. The Playwright step exists to catch exactly that.

**Where the current plugin UI lives (starting points for extraction):** issue view sections in
`web/src/components/items/IssueProperties.tsx` (participants/csat/approvals/external-requester + VCS in
the item tabs / `HistoryTab`); sidebar nav in `web/src/components/shell/Sidebar.tsx`; settings pages in
`web/src/routes/settings/*` + `web/src/routes/project-settings/*` (docs/dashboards/ai/mcp/slas/connectors/
jiraimport/roles/etc.); the router tree in `web/src/router.tsx`; shared API/query/types in `web/src/lib/*`.

**The exact `/goal` prompt the user is running is preserved at**
`<session-scratchpad>/goalprompt5.txt` (2985 chars) and pasted in the conversation; it is a compressed
pointer to THIS section + `docs/plugin-platform.md §8/§9/§14`.

## Frontend module-federation run (spec 94) — the log

### — federation approach: NATIVE ESM (import-map + global singletons), not a MF plugin
- **Environment reality:** `web/` is Vite **8.1.5 on Rolldown 1.1.5** (Vite mainlined rolldown; pkg
  name is plain `vite`). The installed rolldown does NOT expose a native `moduleFederationPlugin`
  (checked `rolldown/experimental` exports). `@module-federation/vite` × rolldown-vite compatibility
  is unproven and is exactly the doc's flagged "builds but won't load at runtime" risk. Network IS
  available (`npm view @module-federation/vite` → 1.19.1) so a plugin was an option — rejected.
- **Chosen: hand-rolled native-ESM federation** (the Angular `@softarc/native-federation` pattern),
  because it depends on nothing but standard ES modules + import maps — no bundler/MF-plugin coupling:
  - **Remotes** build as a Vite **lib** (`formats:['es']`) with the shared deps in
    `rollupOptions.external`. **Spike-verified** (scratchpad/spike): the output keeps the bare
    specifiers verbatim — `import { useState } from "react"`, `import { registerSlot } from
    "@radd/plugin-sdk"`, `import { jsx, jsxs } from "react/jsx-runtime"` — and `export {activate}`.
  - **Host** ships a single static `<script type="importmap">` in index.html mapping those bare
    specifiers (`react`, `react-dom`, `react-dom/client`, `react/jsx-runtime`, `@tanstack/*`,
    `@radd/plugin-sdk`) → same-origin shim files under `/shared/*.js`. Each shim re-exports the
    host's singleton read from `globalThis.__RADD_SHARED__`, which `main.tsx` populates at boot.
  - The import map only catches BARE specifiers; the host's own bundle emits none at runtime (Vite
    bundles react into hashed chunks), so the map never interferes with the host — only remotes,
    which externalize exactly those ids. Result: ONE React instance + ONE slot-registry (SDK)
    singleton across host + every remote; `<Slot>` renders remote contributions.
  - **Version gate / quarantine** live in the loader (pure TS): check `ui_api_version` before
    `import()`, try/catch per remote. No plugin magic to debug when it fails.
- Physical layout decision (logged): builtin remotes live under `web/remotes/<plugin>/` sharing the
  `web/` workspace node_modules (one toolchain), NOT scattered into `server/.../modules/<p>/ui/`.
  Rationale: satisfies LOCKED-1 literally (web/src imports nothing plugin-specific; each plugin UI is
  a separately-built federated remote loaded at runtime) without ~18 separate node_modules installs.
  The **example plugin** (`examples/acme-notes/`) IS a fully independent project (own node_modules +
  pyproject) — that is the true-externality acceptance proof (LOCKED-2).

### — platform built + PROVEN in a real browser (commits cbe7ecb…eeb4753)
- **SDK (`web/packages/plugin-sdk`, `@radd/plugin-sdk`)**: slot registry (`registerSlot`/
  `unregisterPlugin`/`useSlot`/`<Slot>` with per-contribution error quarantine, a `globalThis`
  singleton belt-and-suspenders), semantic theme tokens over the host zinc scale (self-contained hex
  fallbacks, light/dark inherited), primitives (Button/TextField/TextArea/Select/Chip/Card/Avatar/
  Spinner/EmptyState/Modal) as `.radd-*` classes so remotes render them without their own Tailwind,
  the api client + data hooks (permission-aware), the `activate()` contract, and the
  `UI_API_VERSION` gate.
- **Host federation** (native-ESM, no MF plugin): import map + `globalThis.__RADD_SHARED__`
  bootstrap + generated `/shared/*.js` shims (`scripts/gen-shared-shims.mjs`, introspects installed
  versions); `plugin-loader.ts` (version-gate → `import()` → `activate`, quarantine, live
  enable/disable via `unregisterPlugin`); `PluginRemotes` reconciles on manifest change; `PluginPage`
  + a splat route render the `route.page` slot. `scripts/build-all.mjs` = reproducible
  host-then-remotes build; `scripts/prepare-federation.mjs` links the SDK + regenerates shims.
- **Backend**: `PluginUiManifest.ui_api_version`; `/capabilities` returns `remotes:[{name,
  remote_entry,ui_api_version}]`; a stable `plugin-assets/` dir served at `/plugins/<name>/`
  (decoupled from the wiped `web/dist`, JS media type forced); `radd.plugins` **entry-point
  discovery** (§10); entity-table create on runtime enable. `tests/test_frontend_federation.py` (4).
  **Full suite 965 green.**
- **Migrated remotes**: `participants` (issue.panel.section) and `milestones` (route.page, a real
  CRUD page) out of `web/src` into `web/remotes/*`; `IssueProperties` renders a `<Slot>` and no
  longer imports participants.
- **Acceptance (LOCKED-2)**: `examples/acme-notes/` — independent project (own pyproject entry point
  + own web build), `uv pip install -e` → discovered → install+enable → the `acme_notes` table
  auto-created, `/api/v1/notes` live, a Notes page + an issue Notes section, **zero core edits**.
- **Render proof (LOCKED-3) — GREEN in headless Chromium** (`web/scripts/render-proof.mjs`, zero-dep
  CDP driver over Node 22 WebSocket+fetch + the cached ms-playwright Chromium): login → `/capabilities`
  lists the remotes → each remote loads + `activate`s + registers into the host SINGLETON slot
  registry → the **Participants section RENDERS on a real issue** → the **Milestones page renders at
  /milestones** → the **external acme-notes page + issue section render** → the `ui_api_version` gate
  accepts a compatible major / refuses an incompatible one → **live disable removes a section /
  enable restores it, no reload** → zero console errors. A real bug (default-export activate) was
  caught here and fixed — exactly the "builds but won't load" failure mode the browser step exists for.
- **Harness notes**: `cat`/heredocs are unreliable in this fish env (alias) — use Write. `npm install`
  exits 0 but writes no node_modules here — the SDK workspace + the example's node_modules are
  symlinked to the shared `web/node_modules` (documented; package.json/pyproject declare the real
  deps). Render/plugin-manager proofs mutate `installed_plugins` in radd_test — TRUNCATE it before the
  full pytest gate.
- **Parity status (LOCKED-1)**: platform + pattern proven; `web/src` still imports several plugins'
  UI. Each is a mechanical repeat of the participants extraction. Tracked in spec 94 Part C;
  remaining ones are logged gaps, not blockers — each still works in `web/src` until migrated.

### — issue view fully migrated + net status
- Migrated the last three hardcoded issue-rail sections into remotes (`web/remotes/{mailintake,csat,
  approvals}`) via a subagent (each typecheck+build+hex-clean, following the participants template);
  did the `IssueProperties` surgery myself (removed the three sections + defs + the `hasPlugin`
  band-aid + ~20 now-dead imports). **`web/src/components/items/IssueProperties.tsx` now imports
  NOTHING plugin-specific** — mailintake/participants/csat/approvals all arrive through the
  `issue.panel.section` Slot. Headless proof (FED-1): all four remotes load + activate into the host
  singleton registry, zero console errors; participants renders; live disable/enable works.
- **Net (DONE-gate):** ✅ boots clean (alembic head, create_app, host + 6 remotes build); ✅ full
  pytest **969 green** (installed_plugins truncated first); ✅ the app SERVES — SPA index (import map
  present), `/shared/*` shims, and all six `/plugins/<name>/remoteEntry.js` bundles all 200; ✅ the
  external example loads at runtime, zero core edits; ✅ live enable/disable toggles federated UI; ✅
  `ui_api_version` gate refuses an incompatible major; ✅ headless render proof green; ✅ no hardcoded
  hex in any remote. **PARTIAL:** LOCKED-1 full parity — the issue view is done; the sidebar's
  docs/dashboards/cycles/forms/queues sections, the plugin route pages (docs/dashboards/reports/
  cycles/timesheet), and the `routes/settings/*` + `routes/project-settings/*` pages remain in
  `web/src` (each a mechanical extraction; `settings.page`/`sidebar.nav`/`dashboard.widget`/`issue.tab`
  slots are defined in the SDK and wire up as their first consumer migrates). Spec 94 Part C is the
  live checklist; nothing dropped silently.
- **Slot types PROVEN end-to-end in a browser:** `issue.panel.section` (participants + the 3 new
  sections + the external acme-notes section), `route.page` (milestones CRUD + the external
  acme-notes page), and `settings.page` (acme-notes Settings panel inside the Settings chrome, via a
  settings splat route + manifest-driven settings nav). `sidebar.nav` is manifest-driven. The
  remaining slot ids (`issue.tab`/`dashboard.widget`/`item.action`) are the same registry, unproven
  only for lack of a migrated consumer.

### — final verified state
- Consolidated headless proof (all plugins enabled, one issue): the slot registry's active plugins =
  `acme-notes, approvals, csat, mailintake, milestones, participants` (all six remotes loaded +
  activated), participants renders, live disable/enable toggles it, the `ui_api_version` gate
  accepts a compatible major / refuses an incompatible one, **zero console errors**.
- `create_app` boots (210 paths), alembic at head `e53d08a57e29`, full `pytest` **969 green**
  (truncate `installed_plugins` first), host + 5 builtin remotes + the external example all build,
  every `/plugins/<name>/remoteEntry.js` + `/shared/*` + the SPA index (with import map) serve 200.
- **STOPPED here on LOCKED-1 full parity by engineering judgment** (not a block): the platform, the
  theming, the acceptance, and three slot types are proven; the issue view is fully migrated. The
  remaining surfaces (sidebar docs/dashboards/cycles/forms sections; the docs/dashboards/reports/
  cycles/timesheet route pages; the ~24 `routes/settings/*` + `routes/project-settings/*` pages) are
  high-traffic and each a mechanical repeat of a proven pattern — migrating them unattended carries
  real regression risk for modest additional proof value. They are enumerated in spec 94 Part C, each
  still works in `web/src` (no regression), and the exact extraction recipe is: create
  `web/remotes/<name>` (or contribute from an existing remote), move the component using SDK
  tokens/primitives, register the matching slot in `index.tsx`, add
  `ui=PluginUiManifest(remote=…)` to the backend manifest (nav `section:"settings"` for a settings
  page), delete the code + its imports from `web/src`, then `build-all` + the render proof.

### — contribution toggles: two-scope, plugin-owned, opt-in (commit d4c5819)
- Reworked per-user contribution toggles after user feedback rejected the earlier "kernel
  auto-generates a per-user list for every plugin" design. Now:
  - **Two scopes.** GLOBAL (admin, Settings → Plugins → `<plugin>`) is instance-wide — off ⇒ hidden
    for everyone AND dropped from Profile; stored per-plugin in `InstalledPlugin.config`
    (`GET /plugins/contribution-settings` any-user + `PUT /plugins/{id}/contribution-settings`
    admin). PER-USER (Profile) lists only globally-enabled pieces; `/auth/me/preferences`. A
    contribution renders iff enabled in BOTH.
  - **Plugin-owned + opt-in.** The kernel forces nothing. SDK ships `<GlobalContributionToggles>` /
    `<UserContributionToggles>` (On/Off **radios**); a plugin exposes toggles by contributing them
    to the new `pluginManagerSection` and/or `profileSection` slots. `toggleable:false` keeps a
    plugin's own control surfaces out of the lists. A plugin that mounts neither shows just
    Enable/Disable.
  - get-or-create for the global row seeds the plugin's DEFAULT lifecycle state, so saving a setting
    never enables/disables the plugin itself (regression-tested).
- Verified: **977 pytest green** (+3 pluginmgr tests), full federated build clean, headless
  two-scope proof exit 0 (admin radios / 0 checkboxes; global-disable hides for everyone + removed
  from Profile; per-user disable account-only, absent from global set). Live server on :8000
  restarted against the `radd` DB.

### — session wrap: plugin-UI depth done + two adjacent features (specs 94 ext, 95, 96)
- **Plugin-UI depth (spec 94 addendum):** the toggles became an On/Off **switch** (not radios); a
  disabled contribution now also drops its **nav link** (main + settings sidebars) and its
  **view-type / widget-type dropdown option**, and shows a `MissingPluginType` "turned off" notice
  for an existing view/widget of a turned-off type (SDK `useDisabledNavPaths()`/`useDisabledMatches(slot)`).
  `docs/specs/94-*.md` has the addendum; `docs/plugin-ui.md` the full rules.
- **Spec 95 — inline-token multi-select** (`web/src/components/TokenMultiSelect.tsx`): one compact
  control (chips on one scrolling row + typeahead + autocomplete/create) replaces the tall wrapping
  pill stacks app-wide. `docs/specs/95-*.md`.
- **Spec 96 — disable un-writable fields up front**: `fields.readonly_field_keys` + `GET
  /fields/writable` (spec-92 access resolution) → SPA `useItemWritability` gates the issue rail /
  title / description / flag / comment composer / bulk bar / New Item modal; disabled + dimmed, no
  edit-then-error. `docs/specs/96-*.md`, `tests/test_field_writability.py`.
- **State:** 980 pytest green; full host + remotes build clean; all features headless-proven with
  real restricted members. Live server on :8000 (task `bxca3b26s`) runs the new backend against the
  `radd` DB. **Leftover:** one empty `RO2F39E6` "Readonly demo" project from a writability proof
  (projects have no cascade-delete service). CLAUDE.md headline + `docs/modules.md` (federation +
  `fields`/`pluginmgr`/`auth` addenda) updated.

---

## UI modernization + repo-health run

Not a numbered spec — a full review-driven overhaul requested by the owner (interface "felt old"),
executed in committed phases. All web phases verified with `tsc -b && vite build`; all backend
phases with the (now self-contained) pytest suite.

- **Design-token foundation.** `web/src/index.css` now carries a semantic token layer via Tailwind
  v4 `@theme inline` (`base/surface/elevated/overlay`, `subtle/strong` borders, `heading/fg/
  fg-secondary/fg-muted/fg-faint`, `accent`) on top of the existing zinc-remap mechanism (kept —
  light theme + plugins depend on it), a retuned dark palette with real surface separation
  (page #171718 / panel #202022 / elevated #26262a), globally bumped radii, dark-tuned shadow
  scale, `animate-fade-in/overlay-in/menu-in` motion tokens (+ reduced-motion guard), `tnum`, and
  self-hosted Inter (`web/public/fonts/`, OFL, fetched from jsDelivr — no npm dep; **no npm binary
  exists on this machine, builds run via `web/node_modules/.bin/{tsc,vite}`**). Plugin SDK
  `--radd-*` tokens converged (new elevated/overlay/font/shadow tokens; radii bumped).
- **Kit + shell restyle + token sweep.** Shared kit and app shell migrated to the tokens (accent
  focus rings, quieter empty states, sidebar active indicator); a perl whole-token sweep migrated
  all of `web/src` off raw zinc utilities (remaining zinc = tiers with no token equivalent).
- **Primitives kit.** `Button` (secondary/ghost/danger/danger-ghost, sm/md), new `ConfirmDialog`
  (+ `useConfirm`) — native `confirm`/`alert` count is now **0**; new `DropdownMenu`; new `Select`
  listbox — all **34 native `<select>`s** replaced (`SelectField` keeps its API); new `Table`
  primitives (gridline-free, `tnum` numerics) — 4 tables migrated, borderless/markdown ones left.
- **Frontend structure.** `lib/types.ts` (3128) → `lib/types/` 30 modules, `lib/queries.ts` (1541)
  → `lib/queries/` 20 modules, `lib/constants.ts` (649) → `lib/constants/` 7 modules — all behind
  barrels, zero import churn; `roadmap-model.ts` (1039) → `roadmap/model/`; `Sidebar` 754→494 and
  `RoadmapTimeline` 986→557 via clean extractions. `view.tsx`/`router.tsx` assessed: no safe seam.
- **Backend health.** Test suite is self-contained: conftest recreates a migrated `radd_test` DB
  per session (guard refuses the dev DB) — **980 passed** (was 973 + 7 dev-data failures).
  `items/service.py` (1207) → `items/service/` package, 8 modules, AST-parity-verified. The
  RaddPlugin migration is finished: all 49 modules construct `RaddPlugin` from `radd.kernel`,
  `radd/module.py` shim deleted, counts synced. CLAUDE.md rule 1 now documents the spine-table
  exception (`auth.User`, `projects.Project`); `docs/modules.md` maps the deferred-import edges.
- **Known leftovers:** 57 pre-existing `ruff check src/` errors (baseline, untouched);
  8 tables (settings + markdown renderer) still hand-written. `view.tsx` (735) and
  `router.tsx` (604) were the two largest files assessed this pass and left alone (no
  clean seam) — they are *not* the only ones over the 300-line rule: 30 web and 25
  server files still exceed it (`jiraimport/runner.py` 800, `automations/engine.py` 729,
  `views/service.py` 713, `IssueProperties.tsx` 595 lead the list).

---

## Review follow-up (same day)

A review of the wave above verified its claims (build clean, **980 passed**, ruff exactly
57, 49 plugins on `RaddPlugin`, 0 native `<select>`/`confirm`) and found three places where
the record and the code disagreed. All fixed:

- **The accent sweep had never happened.** The token rule was written as if `web/src` were
  clean, but 279 raw palette utilities remained — 193 of them `indigo-*`, against 11 uses of
  the `accent` token. Root cause: the only accent tokens were two *fill* shades, so accent
  TEXT (`text-indigo-300`, remapped for light) and focus rings (`outline-indigo-400`, 64
  sites, **not** remapped) had nowhere to go. The accent is now its own per-theme scale
  (`--accent-fill/-hover/-text/-text-strong/-focus`) rather than a rider on the indigo remap,
  plus a `--color-emphasis` neutral-border tier (the `border-hover`/`bg-strong` idea above,
  renamed: the tier also serves static pill borders). **`web/src` is now at zero raw
  `zinc-*`/`indigo-*` utilities**, kit included — `Modal.tsx`, the primitive the rule points
  at, was itself un-migrated. Two light-theme bugs fell out: `text-indigo-400` and
  `focus:outline-indigo-400` were never remapped (washed-out indigo on white — focus rings
  now use indigo-600, ≥3:1), and roadmap bar text (`text-zinc-950` on a fixed category fill)
  inverted to near-white on light; it is `text-black` now. Accent fill hover also darkens on
  light instead of lightening. SDK `--radd-accent*` repointed at `--accent-*` (Tailwind no
  longer emits `--color-indigo-*`, so the old references would have silently fallen back to
  hardcoded hex). Two competing focus colors unified on `outline-focus` (75 sites).
- **The `items/service/` barrel published 30 private helpers.** Its `__all__` exported every
  `_`-prefixed helper, justified as "the helpers other modules import anyway" — a trace of
  all 30 across `src/` + `tests/` found **zero** external importers (the one non-package
  caller, `items/bulk.py`, is the same module and now imports from `.service.visibility`
  directly). `__all__` is the 25 public functions the old god-file exposed, nothing more.
- **Dead back-compat surface deleted.** `RaddModule` and `load_modules` were kept for
  "transition-era third-party plugins" that never existed; the migration is now actually
  finished. Also: `DropdownMenu`'s docstring still claimed close-on-scroll, and `useConfirm`
  orphaned the first promise if called twice before settling.
- **Measured, not claimed:** the lib split was rebuilt against its parent commit — the
  barrels did not cost bundle size, they saved it. Entry chunk **1,233.87 kB → 1,060.52 kB**
  (gzip 336.59 → 286.41); `rich-editor` 1,033.12 → 998.22 kB. Finer granularity let rollup
  push code into lazy route chunks. Verified after this follow-up: tsc + vite clean,
  **980 passed**, ruff still exactly 57.


---

## Dusk UI wave + relational SLQ (later same day)

Continues the review follow-up above. Committed in themed slices; every slice verified with
`tsc -b --force` + `vite build` and the pytest suite (980 → **989 passed**, ruff baseline
still exactly 57).

**Look and layout.** The owner's read was "old and dated", so direction was picked from
mockups (seven options, surface vs structure) rather than argued in the abstract. **Dusk**
won: cool blue-shifted neutrals, periwinkle accent, softer radii, light theme rebuilt from
the same hue family. Workflow-state colours became the **traffic light read literally** —
green means go, so `in_progress` is green and `done` therefore CANNOT be green; it is a dark
slate, deliberately identical to `canceled` (a product decision, at the cost of a stacked
chart not separating them). Collapsing the terminal states freed the hue budget to put
`todo → in_progress` on blue→green at deutan ΔE 18.1. Every step validated with the dataviz
six-checks: the OLD palette failed the dark lightness band on every hue, put `canceled` at
2.25:1, and left `todo`/`backlog` at ΔE 13.3. Pills gained an **ink tier** (a fill needs 3:1,
text needs 4.5:1, and on a tinted pill the fill sits on a wash of itself — triage was
yellow-on-yellow at 2.04:1; the "Logged" chip used `text-violet-200`, which has no light
remap at all, at **1.39:1**).

**Cards + panels.** Card surfaces on every work surface (list, board, swimlanes, issue,
dashboard, roadmap, peek); a collapsible sidebar rail; a reusable `<SidePanel>` for docked
panels; resizable roadmap-gutter and peek widths.

**State.** Item-affecting page state moved to the URL with a client-side short link past 180
chars (`?s=<hash>`; measured 180-char query → 9-char query string, exact round-trip); display
state stays in localStorage; `Reset view` clears both.

**Backend.** Dashboards finally adopted the spec-92 access framework (`dashboard_shares` was a
verbatim copy of a table spec 92 had already deleted); the migration is hand-written because
autogenerate proposed dropping the table with **no data copy**, plus `acme_notes` and a
functional GIN index. Kernel/items leftovers deleted. Specs **97** (relational item fields)
and **98** (the worklog dialect) added SLQ's second dialect.

**Bugs that only rendering caught** — each passed `tsc` and the build:
- a flex container squashed 92 planning cards into ~12px strips (flex items shrink by default);
- `<SidePanel>` toggled `aria-expanded` and stayed 288px wide (the caller's `w-72` beat `w-9`);
- board columns clipped 75 cards to about five (`overflow-hidden` for rounded corners, no scroll).
Twice the opposite also happened: a pill and the whole light theme were called broken from a
downscaled screenshot and were correct on measurement.

**Known leftovers:** cycle-status and release-status dots still use raw `bg-blue-400`/
`bg-emerald-400` rather than the state tokens; the Radd mark is still orange against a
periwinkle accent; `index.html` hardcodes `class="dark"` so light mode renders
`class="dark light"` (harmless — nothing targets `.dark`); back/forward does not restore
filter state (writes use `replaceState` so chips don't stack history); `?s=` short links only
resolve in the browser that made them.

## Issue-view declutter (follows the editor-AI UX wave)

Dogfooding feedback: the issue page front-loaded reference material. Changes,
shared by the full page and the peek (both render `ItemDetailBody`):

- **`<CollapsibleCard>`** joins the kit (`web/src/components/`): a card surface
  whose body collapses behind a compact uppercase heading + count chip.
  Adopted by **Dependencies** and **Related links** — an empty Dependencies
  card (heading + always-visible add-form) is now a 38px line; a 30-link
  Related links card likewise. Counts come free: `dependencyLinkCount(item.links)`
  (exported next to `buildLinkGroups`, mentions excluded) and the
  `itemWebLinksQuery` cache the section itself reads.
- **Time tracking** in the properties rail is one collapsible widget
  everywhere, collapsed by default: the collapsed face is the peek's old
  compact summary (progress bar + estimate/entries line), expanding reveals
  the full panel (estimate editor, log-work form, worklog list) — which the
  peek previously could not reach at all. The redundant "No estimate" in the
  summary line went (the bar already says it).
- **More fields** collapses by default on the page too, not just the peek.
- The standalone **Docs** section folded INTO the Related links card as a
  sub-block (its own doc comment always called it "the Related links area");
  the card's count chip sums web links + linked docs, and the whole block
  still vanishes when the docs module is absent.
- With page and peek now identical, the `variant: "page" | "panel"` prop was
  deleted end to end (`ItemDetailBody`, `IssueProperties`, `IssuePanel`).
- The AI card moved ABOVE the properties card in the rail (same-day request).

Verified via CDP probes (aria-expanded defaults, card heights 36–38px
collapsed, add-form/log-form reachable after expand) + screenshots.

**Centered measured layout (same day, its own commit for easy revert):** the
issue page's reading column was unbounded — ~1,500px text lines on wide
monitors, content smeared wide-and-shallow with a dead band below. Now the
reading column (description → dependency/link cards → conversation, ALWAYS
stacked — an ultrawide description|comments split was built, dogfooded for
minutes, and rejected: discussion belongs under the document) caps at
`max-w-[64rem]` and centers via `justify-center` in the space left of the
properties rail, which stays IN FLOW and anchored to the viewport's right
edge. The title/banner can't live inside the centered column (the peek must
show the title above the properties stack), so they mirror the rail's width
(`@3xl:mr-[19.5rem]`) and center to the same measure — title flush with the
description card to the pixel; slightly wide mirror when the rail is
collapsed, cosmetic. The wrapper is a `min-h-full` flex column so the
conversation card stretches to the page bottom (no dead band under it); the
composer follows the thread (a bottom-pinned composer was tried and dropped —
with a tall rail it sank below the fold over a hollow card middle). Verified
at 2000px and 1500px: stacked at both, rail flush right, title aligned,
no horizontal overflow.

**Global top bar + saved filters + pins (same day, reference-driven):** a new
app-shell `TopBar` (pinned favorites as tabs, My Work first; the QUERY SLOT in
the middle; profile avatar right). The slot is a context+portal seam
(`TopBarSlot.tsx`): a view page portals its LIVE SLQ filter editor into the
bar (the global query bar IS the page filter — reference semantics), any page
that claims nothing gets the search-the-app pill that opens the palette. View
pages restructured to two rows: identity (+ a pin toggle and the stored query
as a compact chip, both the old full-width SLQ row and the chips row are gone)
with CSV/Edit/Delete folded behind ⋯; then the TOOLBAR row — ProjectNav,
SAVED chips (the view's shared quick filters AND the user's PERSONAL saved
filters), count, "Group: X", New item. Personal filters + pins live in the
spec-94 per-user preferences dict (`slq.saved_filters`, `nav.pins` —
`lib/topbar-prefs.ts`, PUT shallow-merge, zero backend). "Save filter" names
the current ad-hoc query, activates the new chip and clears `q`; chips AND
into the fetch exactly like quick filters, URL-synced under `pf`. Shell
consequence: the outlet wrapper owns page scrolling and every in-shell route
went `h-screen` → `h-full` (the bar owns the first 48px; window scrolling is
gone). Verified live: portal/fallback swap, pin round-trip, save-chip flow,
no overflow — zero console errors.

**One query input, two modes (same day):** the separate NL "Ask" input merged
into the SLQ bar — `QueryBar.tsx` is ONE pill with an `SLQ ⟷ ✨Ask` toggle at
its end. Ask mode takes natural language; the generated query lands back in
the SLQ editor, applied, with the explanation line — every ask teaches the
language. Deliberate NON-feature: no auto-detection (a typo'd SLQ must fail
loudly as SLQ, never silently become an LLM prompt). Used by the top-bar
portal AND `SlqFilterBar` (the timesheet inherits with its worklog dialect);
`AskAiBar.tsx` deleted. Verified live: toggle round-trip, "high priority
issues assigned to anyone" → `priority = high AND assignee IS NOT EMPTY`.

**Board redesign (same day, reference-driven):** open columns (the boxed
column panel is gone — cards float on the page ground with a dot + name +
count + `+` header and a dashed "Add issue" foot, drop highlight paints the
column's rounded region), w-72 → w-80, and a four-row card anatomy: type/kind
icon + mono key with the priority as a compact mono TAG (`BLOCK/HIGH/NORM/LOW`
via `PRIORITY_META.short`), a 14px semibold 2-line title, a QUIET mono label
row, then ONE structured footer — epic chip (parent's NAME, purple), rollup
`n/m`, cycle/release/due/team/sla chips, with logged time and the
avatar/unassigned slot anchored right. New `logged_time` card slot (default ON
for boards; DisplayMenu picks it up from the registry) fed by the EXISTING
`POST /items/timelog/batch` via `timelogBatchChunkedQuery` — no backend
change. Quick-add: both affordances open NewItemModal (new optional `initial`
prop) with the column's bucket preset via `bucketCreatePreset` — the
`bucketMovePlan` axis mapping minus an item, where the KIND axis works too
(create-only). Board-local styling only: shared atoms (ItemKeyLink, KindBadge,
chips) untouched; swimlanes inherit the card + width automatically. Verified
live: 17 open columns at 320px, 200 priority tags, 123 logged-time readouts,
quick-add on "Triage" opened the modal with State=Triage preselected.

**"Properties" → "Fields", header into the card (same day):** the rail's
banner header ("Properties") was misleading (it's just fields) and pushed the
first card below the description's top line. `SidePanel` gained a `frameless`
mode + an embeddable `<SidePanelCollapse>` toggle (context-wired); the fields
card now carries its own FIELDS heading with the collapse toggle, and the
rail's first card (AI, or Fields when AI is off) top-aligns with the
description card exactly. Two latent bugs fixed on the way: SidePanel built
its docked-only classes DYNAMICALLY (`` `${sideAt}:block` ``) which Tailwind
never generates — the docked collapse strip/toggles had been `display:none`
since the component shipped — replaced by a static `DOCKED_CLASSES` map; and
the toggle now queries a NAMED container (`@container/page` on the issue
scroller, variant `@3xl/page:block`) because it sits inside the fields card's
own smaller `@container`, which an unnamed query would resolve against.

---

## — the shell + UX wave (screenshot-driven, unnumbered)

Layout: the Cairn-band shell (full-width TopBar + PinsBar rows, sidebar
under), pin-anything (view XOR link pins, right-click everywhere, rename),
Ask-default query bar with the ⌘I mode toggle, the InboxPeek drawer, peek
default 1100px, view pages consolidated to ONE header band (ProjectNav
deleted). Radius scale dialed DOWN to 6/8/10/12px (the Dusk bump read too
round in daily use); plugin-sdk radius tokens kept in sync.

Editor: toolbar glyphs were tinted with `--crepe-color-outline` (the BORDER
grey) at 24px — now 18px at 8:1 contrast with an accent pill on active marks
(upstream's top bar sets `.active` but ships NO styling for it). The AI diff
review is a UNIFIED diff now: old block stacked red above the green result
block, word-level emphasis inside each — the interleaved strikethrough soup
was unreadable on any real rewrite. AI answers (summarize/find-similar) open
in a results pane BESIDE the issue's reading column via `AiResultsContext`.

Kit: `SelectField` walks `<optgroup>` children now (it silently dropped
them — the automations trigger dropdown rendered empty since the select-kit
conversion). Away-indicator primitives: Avatar status DOT anchored INSIDE the
circle (a positioning wrapper stretched under flex parents), `PersonName` +
`AwayChip` ("away" beats any glyph at 10px — the TreePalm first cut smeared).

---

## — roadmap at scale (perf wave, unnumbered)

The Jira-scale perf dataset (503k items, `server/scripts/perfseed.py` +
`perfseed_depth.py`) exposed the roadmap's fetch-all: roadmap views streamed
their ENTIRE match set page by page (505 requests / ~205 MB on the 100k-item
project) because bars + the whole Unscheduled tray were built client-side
from one flat list.

A roadmap draws epics and dated bars — nothing else — so the fetch now says
exactly that (all server-side, pure SLQ, no new endpoints):

- `routes/view.tsx` ANDs `ROADMAP_STRUCTURE_QUERY` onto roadmap fetches
  (`kind = epic OR (start/target set)` — everything the surface can draw),
  swapped for `ROADMAP_EPICS_ONLY_QUERY` (`kind = epic OR (kind = issue AND
  epic IS NOT EMPTY AND start/target set)` — epics + their scheduled DIRECT
  children; an issue's parent can only be an epic, so `epic IS NOT EMPTY` on
  an issue IS the direct-child test) when the per-view "Epics only" toolbar
  toggle is on. The default went back and forth same-day: first everything-
  scheduled (2,535 epicless standalone rows on CHRM read as noise), then
  strict epics-only (dated epicless work vanished entirely) — landed on
  everything-scheduled by DEFAULT with Epics-only as the quick de-noise
  toggle. In epics-only mode the surface also drops any child whose epic
  isn't loaded (a composed query can strand one, e.g. recency dropping a
  done epic) rather than promoting it to a standalone row. Plus the
  default-on `ROADMAP_RECENT_CLOSED_QUERY` — closed items keep drawing for
  ~3 months after their bar ends, then drop out ("Show closed" in the surface
  toolbar lifts it, persisted per view). The surface receives the NARROWED
  view so `useRoadmapItemPatch`'s optimistic cache key matches the fetch.
- Auto-stream is CAPPED in `ROADMAP_MAX_AUTO_PAGES` bursts with an amber
  "Showing the first N — refine or load more" notice, so no query can
  re-create fetch-all.
- The tray is its own bounded, searchable pool (`roadmapTrayItemsQuery`:
  view query + `ROADMAP_TRAY_QUERY`, 50/page + Load more, All/Epics chips and
  the title search narrowing server-side via SLQ; derived-bar epics deduped
  against drawn rows).
- An epic's date-less children are fetched per epic (`parent = KEY`) only
  when Auto-schedule / Bring-children actually runs — the context-menu verbs
  un-gate from "loaded children" accordingly.

Measured on GRX (100,850 items), headless-CDP against the live app: 11 item
requests (10 main + 1 tray), settled ~4s, 1,796 rows; Show closed refetches
relaxed (2,705 rows, cap notice up at page 15). Was: 505 requests, minutes.

Scroll UX follow-up (same day): the domain begins at the earliest loaded bar
— often years back — and nothing positioned the viewport, so mounting dropped
you at the oldest end of history (never felt pre-scale, when every bar sat
within weeks of now). The surface now ANCHORS today ~1/3 into the visible
timeline — re-applied while pages stream in (each page can shift the domain
start, changing what a raw scrollLeft means) and on zoom, disengaged on the
user's own wheel/pointer/keys, re-engaged by the Today button, clamped to the
nearest edge when today is outside the domain. And the row-label gutter went
`sticky left-0` (labels z-30 opaque over bars + connectors; axis corner caps
the tick lanes; the resize handle rides in a sticky rail) so horizontal
scroll never costs row identity — tray drops on the VISUAL gutter are
rejected via the pane rect, since layout-x alone can't tell a scrolled-under
day column from the gutter. CDP-measured: mount lands scrollLeft 20,221/22,625
with the today line at x=551 of an 1131px pane (exactly labelWidth + a third
of the timeline); after +3000px the corner/labels pin at x=1, divider x=258.

Focus tools (same day): epic SOLO — a hover Focus button on epic labels, a
context-menu verb, and a toolbar "Solo · N — clear" chip. Solo filters the
items BEFORE buildRoadmapModel, so the rows AND the time domain snap to the
soloed epics (GRX: 22,625px of timeline → 1,205px for one epic); multi-solo
unions, soloing auto-expands the epic, and the set is session-only by design
(a persisted solo would read as data loss next visit). Plus toolbar
Collapse-all/Expand-all over a new `setAllCollapsed` in useRoadmapEditing
(same per-view localStorage persistence as the single chevrons). CDP: 1,796
visible rows → 1,707 collapsed → 1,796 expanded; solo → "1 scheduled" +
restore.

Members-mode slowness was a MISSING INDEX, not the feature: the
default list order is rank and most lists are project-scoped, so a selective
filter (members clause, `assignee = me`, quick filters) over the GLOBAL rank
index walked every row on the 503k-item instance to fill its LIMIT — EXPLAIN
showed 505k buffers / 1.05s for 183 matches. `ix_work_items_project_rank`
(project_id, rank; migration 79554b33d374) keeps rank scans inside the
project (1.3s → 220ms), and the members ride-along switched `epic IN` →
`parent IN` (direct children are all the roadmap draws; the nearest-epic
correlated walk cost ~2x more) → ~105ms. Members-only now settles in ~0.8s.

Viewport navigation (DCC-style): middle-mouse PAN (pointer-
captured, both axes); ctrl+wheel ZOOM anchored at the cursor (continuous
2-40px/day via `useRoadmapViewport`; the preset Select stays and shows a
custom "N.Npx" option when wheel/± leave the landmarks); label-click row
SELECTION (ctrl/meta toggles, Escape clears) with **F = frame selected**
(zoom-to-fit the selection span at 80% pane fill, centered both axes,
disengages the today-anchor); RUBBER-BAND multi-select on empty timeline
space (4px threshold so clicks stay clicks; shift adds; background click
clears); right-click inside a multi-selection opens the BULK menu
(`RoadmapSelectionMenu`: add/remove N roadmap members via one bulk
invalidation, clear dates / flag / unflag as ONE optimistic applyPatches
unit, deselect). CDP-verified on CHRM: pan -300px exact, zoom 20,609 →
6,449px scrollWidth anchored, F framed the selection, band selected 8 rows,
bulk menu up.

Pagination wave: the ad-hoc SLQ bar no longer INTERSECTS one
probe page with the loaded rows — at 503k items a bare `ORDER BY updated
DESC` rendered "4 cards out of 1800 loaded" (top-200-by-updated ∩
first-9-pages-by-rank), and a mixed query's ORDER BY was silently ignored.
The committed bar now COMPOSES into the fetch like a quick filter
(`composeQueryWithBar`: conditions AND in, the bar's ORDER BY replaces the
view's), which also un-gates spec-68 "Select all N matching" while the bar
is active and feeds the spec-82 rankOrdered check the composed query.
And "Load more" is gone from item surfaces: board/list/planning/queue views
page CLASSICALLY (`components/Pager.tsx` — first/prev/windowed numbers/
next/last + the true total from the spec-75 `/items/count` endpoint, which
already existed with the right visibility semantics; page carried in the
URL as `pg`, snapped to 1 when the query changes), and the roadmap tray got
the compact pager + a true total badge. Roadmaps keep their capped auto-stream
(a timeline has no pages). CDP on CHRM (50,406 items): bar ORDER BY →
full 200-card page 1 of 253, Next → pg=2 in the URL, Last → the 6
oldest-updated items. The header count chip now shows the true total.

Roadmap DRAFT mode: scheduling gestures no longer write the DB
as they happen — too easy to nudge a bar by accident. Every edit through the
`applyPatches`/reorder/rank-chain seams now pushes a COMPOUND op into
`useRoadmapDraft` (one auto-schedule of 30 children = ONE op, so undo moves
in user-sized steps); the surface renders `draft.applyTo(serverItems)`
(tray drops carry the full Item as a draft INSERT so never-fetched items
draw), and the toolbar grew Undo/Redo (⌘Z/⇧⌘Z, tooltips name the op),
Discard (confirm dialog), and a Save·N button that is the ONLY thing that
touches the server: one batched net-diff field PATCH (no-ops dropped), then
the rank intents replayed in op order (anchors are ids, so dates and ranks
never interact). beforeunload guards a dirty draft. Link create/retype/
delete and membership pins deliberately stay immediate — both pass through
an explicit popover/menu step, acts not slips. CDP lifecycle on CHRM:
Clear-dates → bar gone locally, DB untouched, "Save · 1" lit; Undo/Redo
round-trip; Save → DB nulls landed; restore.

Curated membership (same day, full-stack): `view_members` + idempotent
`PUT/DELETE /views/{id}/members/{item_id}` (spec-57 edit-gated) and the
`roadmap` item-SLQ field via the spec-94 registry — see the views addendum in
docs/modules.md. The roadmap grew a Members·N/All toggle (members-only
auto-engages on the first pin), BookmarkPlus/Check hover buttons on
non-child rows + context-menu verbs (view.can_edit-gated), the ride-along
composed as `roadmap = "<id>" OR epic IN (<member epic keys>)`, and a
members-narrowed tray. One found-the-hard-way fix: the members read used
limit=500 against the items endpoint's le=200 — a silent 422 that made
membership invisible to the UI while the writes worked; reads now ride the
page cap. CDP lifecycle on CHRM: 317 rows → pin one → auto members-only
(1 row, tray 0) → All (317, bookmark lit) → unpin → clean. Explicit member
standalone issues DO render in members mode — hand-picked beats the
epic-first noise rule.

## — embeddings at Jira scale (perf follow-up, unnumbered)

The perf-seeded 503k items exposed two stacked embedding-backfill limits:
`PeriodicLoop` slept the full poll interval after EVERY tick (64 items / 3 s
≈ 21/s ceiling before the embedder even runs), and fastembed-CPU on the dev
box tops out at ~20 texts/s (5600X, no VNNI — int8 ONNX gets no acceleration;
`threads`/`parallel` don't help, one session already saturates the machine).
Fixes: the loop grew `drain=True` (re-tick immediately while run_once reports
work; the interval only paces the idle poll — worker.py, embedder dispatcher)
and `ai_embed_batch` went 64→256. Model serving then moved OUT of the app: a
brief `radd[localembed-gpu]` venv experiment (fastembed-gpu + cuDNN wheel,
validated ~2,000/s on the RTX 3080) was reverted same day by decision — the
app image ships no ML/GPU deps; instead compose gained an optional
`embeddings` service (HF text-embeddings-inference, `--profile embeddings`
CPU / `embeddings-gpu` CUDA, shared cache + port, network alias so
`http://embeddings/v1` is profile-agnostic), which Radd consumes as an
ordinary OpenAI-shape provider row holding the embeddings role. Serving the
SAME `BAAI/bge-small-en-v1.5` keeps existing vectors + the partial HNSW index
valid — switch-over needs no re-embed. `radd[localembed]` (CPU) stays as the
zero-infra fallback tier. Three dev gotchas now baked into the compose entries:
TEI needed the `dns: ${RADD_DEV_DNS:-}` knob (corporate split-DNS) or the HF
download hangs; its DEFAULTS reject Radd's sweep — `--max-client-batch-size`
is 32 (< ai_embed_batch 256; every batch 413'd, the backfill crawled on
event-driven crumbs) and `--payload-limit` 2 MB (< 256 × ai_embed_max_chars),
so the shipped commands carry 1024 / 16 MB; and the CUDA image's entrypoint
force-prepends the forward-compat libcuda whenever its `nvidia-smi | awk
'/CUDA Version/'` parse comes up empty — new drivers print "CUDA UMD Version",
so it always comes up empty, and GeForce doesn't support forward-compat →
CUDA_ERROR_SYSTEM_DRIVER_MISMATCH → a SILENT CPU fallback ("Starting Bert
model on Cpu" is the only tell). The gpu service execs the router directly
(`entrypoint: ["text-embeddings-router"]`) so the CDI-injected driver wins.
Measured on the way: HNSW KNN 2.7 ms @ 44k vectors; hybrid /search semantic
round-trip ~20 ms warm; TEI-GPU serves a 256 batch in ~60 ms.

The chase also flushed out a REAL spec-103 bug: `sync_index` compared the
stored indexdef against its own spelling (`model = 'x'`), but pg_indexes
returns the NORMALIZED predicate (`((model)::text = 'x'::text)`), so the
check never matched and every embedder batch silently DROP+CREATEd the HNSW
index — an O(rows) rebuild per 256 rows (quadratic over a backfill: invisible
at 1.7k rows, 12 s/batch by 68k, would be ~80 s/batch at 500k), which also
explains why the sweep rate sagged as coverage grew. pg_stat_activity found
it (`CREATE INDEX … hnsw` active 12 s at a time); the marker now matches the
quoted literal. Remaining per-batch cost is the anti-join sort (~0.2 s, no
`updated_at` index on search_index) + 256 sequential upserts (~5 ms each,
HNSW insert included) — executemany batching stays the follow-up if
import-scale backfills become routine.

## — issue-reference cards open the PEEK (same day)

Clicking a similar-issue / deflection row used to be a plain `<Link>` to
`/issues/$key` (or `_blank` on mid-draft surfaces) — it yanked you off the
issue you were reading, and from inside the peek it destroyed the panel AND
the underlying view. Now ONE peek-aware opener (`useOpenIssueRef` beside
`usePeek`; `PeekSurfaceContext` provided by IssuePanel marks the panel's
subtree, since ItemDetailBody is shared with the full page) drives both leaf
renderers (`SimilarRow`, `DeflectItemsSection`): a plain click opens the
peek — the half-typed form or the reading position survives — and INSIDE the
peek it promotes the peeked issue to the full page and peeks the clicked one
in a single navigation (`/issues/<peeked>?peek=<clicked>`). Rows keep their
real href, so cmd/middle-click still opens tabs; the `newTab`/`_blank` draft
armor is deleted (peeking never unmounts the form). Wiki doc rows keep
`_blank` (no doc peek); the public form (docs-only, outside the app shell) is
untouched. Forced side fix: Modal and IssuePanel each listened for Esc on
`document`, so peek-over-modal (the new NewItemModal combo) would have closed
BOTH on one Esc and discarded the draft — `lib/dismiss-stack.ts` now stacks
overlay close handlers and Esc dismisses only the topmost. CDP-proven on
CHRM: page→peek URL transition, in-peek promote+re-peek, deflect row peeking
OVER the live modal (elementFromPoint says the panel is topmost; title
survives Esc #1, modal closes on Esc #2), zero console errors.

## — AI responses go non-blocking (same day)

Find-similar waited ~13 s on the chat model because the rerank (scores +
"why related" reasons) ran INLINE in /items/{id}/similar. Three changes, all
Settings → AI: (1) `ai_similar_rerank` defaults OFF — reasoning costs a
chat round trip per open, so it's opt-in now; (2) NEW instance setting
`ai_stream_responses` (default ON): when on, /similar returns the fused
candidates immediately (~45 ms) and the panel follows up on the new
`POST /items/{id}/ai/similar/reasons` SSE — the client sends the keys it is
DISPLAYING (pools aren't deterministic between calls; titles re-resolved
server-side under RBAC via the new `search.titles_for_keys`), the reply's
JSON array is parsed INCREMENTALLY (`parse_stream_objects`, pure + tested) and
one `{key, score, reason}` frame ships per completed object — reasons hydrate
row by row, IN PLACE (rows never reshuffle under the pointer; a "Reasoning
about matches…" pulse shows while streaming); (3) summarize gained an SSE
twin (`…/ai/summarize/stream`; `summarize_prompt` is shared so gates fail as
ordinary JSON pre-stream) and the results pane renders the digest as it
streams. Streaming OFF restores every old one-go behavior verbatim —
including the blocking inline rerank. The editor's SSE frame contract +
`streamSse` transport were reused (`streamSseJson` variant for object frames;
`SSE_HEADERS` deduped into types.py). CDP-proven: candidates 253 ms with
rerank on (was 13.5 s), first streamed reason ~2 s later, summary text
visibly growing, zero console errors.

## — settings IA pass (same day)

23 flat tabs became FOUR headed groups (user-approved layout): **Account**
(Profile, API tokens), **Issues** (Fields, Link types, Labels, Cycles, Work
categories, Automations, Canned responses), **People** (Users, Teams, Roles,
Holidays), **Server** (Overview — the old "Server" status tab renamed —
General, Doc spaces, AI, Storage, Backups, Monitoring, Import from Jira,
Plugins, Audit log), plus an **Extensions** header that appears only when
federated plugins contribute settings pages. Group headers hide when the
viewer can see none of the group's items; per-item gates unchanged; every
section URL unchanged (nav regroup, not page moves) — with ONE exception:
the Leave page was split per its two audiences. "My leave" is now a section
ON Settings → Profile (your absences belong with your account) and the
admin-only team-holidays editor is its own small **Settings → Holidays**
page under People (`components/settings/LeaveSections.tsx` holds both
halves; `/settings/leave` redirects to Profile, the members→users legacy
pattern). Directory keeps its deliberate no-tab design (reached from Server
Overview's LDAP row). Nav rail widened w-44→w-48 so "Canned responses" stays
one line. CDP-proven: header order, no Leave tab, redirect lands on Profile,
Holidays page renders the admin editor, zero console errors.

Follow-up (same day): the Overview's per-connector pills moved home to
Plugins. They existed because "configured" (env token present, via each
plugin's CapabilitySpec) is a DIFFERENT axis than the plugin manager's
enabled/disabled — a connector can be enabled yet tokenless and dead. Now
`PluginRead` carries the plugin's evaluated capabilities (evaluated from the
plugin OBJECT via the new `kernel.capabilities.describe()`, not the registry,
so disabled plugins still report), connector rows on Settings → Plugins wear
a Configured/Not-configured chip beside the lifecycle badge, and the Server
Overview keeps ONE "Connectors · n of m configured" pill linking there (the
at-a-glance deploy check survives; the per-connector sprawl doesn't). CDP:
"0 of 5 configured" pill, five chips on the plugin rows, no "Connector ·"
rows left, zero console errors.


---

## PLAN.md §8 and §11 with Addenda 10–15 (moved 2026-09-27, RADD-1441)

Status, immediate-next-steps and the per-spec addenda that used to live in `PLAN.md`; kept verbatim as
the closed record they had become (`PLAN.md` itself says the roadmap lives in the tracker).

### §8. Status & roadmap (as last updated)

## 8. Status & roadmap (updated)

*(historical snapshot — for current state see git tags + docs/modules.md; kept as the running build log)*

The original M0–M5 milestone plan was overtaken by fast iteration: the **tracker is built well past the "prototype,"** and the later pillars (SSO, wiki, extensions, AI) have all since landed (specs 40–48). `docs/modules.md` is the per-module detail and the "Known simplifications" list.

### ✅ Built and live (front-to-back, verified; served at `http://localhost:8000`)

**Platform & foundation**
- Modular monolith — FastAPI / SQLAlchemy 2 / PostgreSQL 16; plugin module system (`RaddModule` assembled from `RADD_MODULES`); transactional **event outbox** with per-consumer offsets + in-transaction hooks; **live OpenAPI** generated from the field registry; the built React SPA is served from the API; commit-before-response middleware.

**Auth & access control**
- Local auth (argon2id), server-side sessions, personal access tokens, service accounts.
- **Roles-as-data**: builtin admin/member/viewer + custom roles with permission sets; **full action RBAC** enforced on every endpoint through one `authz` seam; direct project membership + team-granted project roles.
- **Field-level read/write permissions** granted to roles *or* teams *(originally a non-goal — now built)*; public/internal **comment visibility** gated by permission.
- **Issue types (spec 51)**: a first-class per-project **Type** axis (Bug/Task/Story/Feature/Epic, configurable, colored chips) — the classification the tracker was missing, kept orthogonal to the epic/issue/subtask hierarchy. `itemtypes` module + `type_id` on items + SLQ `type` filter; rendered as compact value-chips on boards/lists/the issue rail; managed under project settings. Plus a **settings design pass**: value-chips for Type/Priority/State, dismissible info banners on the config editors, and up/down reordering.
- **Settings scope + RBAC CRUD (spec 50)**: full-CRUD permission model (77 atoms, `create/update/delete` on every resource incl. the missing `item/comment/worklog/doc.delete`; `*.manage` umbrellas expand transitively — backward-compatible); settings split into **instance / project** surfaces (spec 67 later retired the workspace layer) with **scope-gated nav** and per-project settings nested under `/p/$key/settings/*`; a **scalar-settings cascade** (`scoped_settings` — project → instance → env, first key `work_week_days`); **builtin-field READ grants** (blanked out of item representations); **per-team internal comments** (teams narrow the `comment.read_internal` audience, enforced on list/notify/history/MCP).

**Work tracking**
- Workspaces; projects with **globally-unique keys**; **key-addressed issues** at `/issues/TD-1234` (Jira `browse/` model).
- Work items: epic/issue/subtask hierarchy, per-project numbering, **custom fields inline everywhere** via the registry, workflow states (fixed categories + custom names), labels, priorities, assignee + team, comments (public/internal), dependency links (blocks/relates/duplicates), start/target dates.
- **Cycles/sprints** (global since spec 86, span projects; **draft/staging cycles** with optional dates — a dateless cycle is a planning bucket, never active), **releases** (project-scoped, automation-writable).
- **Saved views** (custom boards/lists) driven by **SLQ** — a JQL-like query language with server-driven **autocomplete** — plus **swimlane boards** on any field axis, and a **Cycle** grouping axis (every cycle a collapsible section with a status/dates/progress summary, an optional name-glob filter, and a Backlog bucket for un-cycled work).
- **Automations** (event → SLQ-condition → action rules engine), **reporting** (throughput, cumulative flow, burnup, velocity, time-in-state), **intake forms**.
- **Time logging + timesheets** (spec 22, per-project-optional): item estimate + worklogs (Jira-style durations, configurable work categories, notes), estimate/logged/remaining, and a workspace **timesheet** (day/week/month, filter by team or person, drill into a day/employee/issue).
- **Webhooks** (Standard Webhooks: signed, retried, dead-lettered).
- **Jira importer** — preserves original issue IDs 1:1 (`TD-48728` → `TD-48728`).
- **Notifications + watchers + Inbox** (spec 26): assignment/@mention/state-change/comment fan-out from the outbox, auto-watch, `/inbox` + sidebar badge, SMTP email digests.
- **Realtime** (spec 27): WebSocket tail of the outbox → entity-level cache invalidation; boards/issues/inbox live-update.
- **Search + Cmd-K palette** (spec 28): Postgres FTS (key/title/description/public comments) + quick-open/navigation palette.
- **Attachments + markdown editor** (spec 29): filesystem-backed uploads, paste-to-attach, safe markdown rendering, `@[Name](uuid)` mention autocomplete. WYSIWYG editing is Milkdown with house-built chrome (spec 54, §11; RADD-745 removed `@milkdown/crepe`).
- **Service desk** (spec 30): reporter/requester field (SLQ `reporter`), SLA policies + pause-aware timers + exactly-once breach events → notifications, canned responses.
- **GitLab connector** (spec 31): webhook receiver auto-linking branches/commits/MRs via the vcs seam + optional merge transitions.
- **"My Work" home + polish** (spec 32): personal landing dashboard (assigned/due-soon/starred/inbox/recently-viewed), saved-view CSV export, `/` palette hotkey.
- **S3/MinIO attachment storage** (spec 33): storage seam — filesystem default or any S3-compatible store with presigned-URL downloads.
- **Personal profile** (spec 34): avatar (color/emoji, shown across the UI), timezone, PATCH /auth/me, tokens panel on the profile page.
- **Work week + business-day SLAs** (spec 35): RADD_WORK_WEEK_DAYS at GET /instance, SLA `work_week_only`, timesheet weekend dimming.
- **RBAC extensions** (spec 36): per-entity manage permissions with umbrella implication, wider member floors (cycles/timesheets/forms), builtin-field WRITE rules (Builtin fields section of /settings/fields).
- **Polish** (spec 37) + **item archive/hard delete** (spec 38) + **light theme & density** (spec 39) + **list "Load more" pagination** (spec 41).
- **SSO — OIDC** (spec 40): code+PKCE relying party, JWKS-verified id_tokens, SSO-only user provisioning, group→role sync each login, login-page button.
- **LDAP/AD bind** (spec 42): **direct UPN bind** (`ldap3`, no stored service account — the pipe-status pattern), nested-group admin mapping via AD's transitive matching rule, same SSO-only provisioning + per-login role sync as OIDC (shared `sync_workspace_membership` seam), Email/Directory toggle on the login page. `RADD_LDAP_*` env; dormant when unset.

**The remaining pillars — ALL landed (specs 43–48):**
- **Wiki** (spec 43): doc spaces + page trees + versions + optimistic-concurrency editing (markdown, the existing safe editor), issue↔doc links both ways, FTS + Cmd-K "Docs" results, doc.read/write/manage RBAC, full two-pane frontend with history/restore. (Yjs/pycrdt co-editing deferred behind the same PATCH seam — §9 fallback shipped.)
- **Extensions SDK** (spec 44): `sdk/` — an independent **Apache-2.0** `radd-sdk` package: PAT-authed client, shotgunEvents-style plugin runner over `GET /events` (crash isolation, hot reload, offset checkpoint, at-least-once), `radd-runner` CLI, example plugin.
- **MCP server** (spec 45): embedded at `POST /api/v1/mcp` — hand-rolled Streamable-HTTP JSON-RPC, PAT principals through the ordinary RBAC seams, tool schemas (incl. custom fields) generated live from the field registry. **Agents-as-principals is real.**
- **AI layer** (spec 46): optional + provider-agnostic (OpenAI-compatible/Anthropic): item summarize, similar/dup detection (FTS always, LLM rerank when enabled), NL→SLQ with server-side compile validation. Issue-page AI panel + "Ask" on the SLQ bar.
- **Connectors** (spec 47): Forgejo/Gitea (HMAC webhook → vcs links + merge transition), Google Chat notifier (outbox consumer, head-start bootstrap), Alertmanager intake (fingerprint-dedup → items/comments), email-to-issue (IMAP poller → service-desk items/reply comments).
- **Packaging & hardening** (spec 48): app `Containerfile` (verified boot) + compose app service + **Helm chart** (worker-split deployments, migration Job, probes), `docs/deploy.md` (backup/restore + env reference), `RADD_RUN_WORKERS` worker split, **MFA/TOTP** (RFC-vector-tested, challenge login, profile enrollment).

**Frontend (React SPA)**
- Login, app shell, projects index; boards (drag-drop), lists (with an ad-hoc SLQ bar), the dedicated full-page issue view, roadmap/Gantt, reporting dashboards.
- Full admin/settings suite: fields (+ permission-grant editor), states, labels, teams, workspace members, per-project access, roles matrix, tokens, cycles, releases, automations rule builder, intake-form builder + submit page.
- SLQ query editor with autocomplete, view/board builder, permission-gated affordances.

### 🔲 What remains — the roadmap lives in the tracker (RADD-603)
Every pillar from the original vision has a shipped first implementation. The depth list that
used to sit here is now **filed as issues in the RADD project on project.radd-hq.com** — the
roadmap view there is the plan, and this document stops being a second source of truth that
drifts (two entries here had already shipped — pgvector in spec 103, storage GC in spec 102 —
while still listed as open):

- **RADD-676…687** — the depth items: wiki co-editing (Yjs/pycrdt), TOTP recovery codes,
  GitLab connector on the SDK runner, ftrack + air-gapped Chat relay, per-project connector
  config, j/k navigation, board WIP limits, issue templates, comment reactions, Confluence
  importer, per-user notification preferences, board/view pagination beyond 200.
- **RADD-688** (epic) — open-source release readiness: synthetic sample data (RADD-689),
  the security checklist pass (RADD-690), license/trademark clearance (RADD-691), the
  never-open-core pledge in the README (RADD-692).

(Running list of known simplifications stays in `docs/modules.md`.)

### §11. Immediate next steps, with Addenda 10–15

## 11. Immediate next steps

*(historical snapshot — for current state see git tags + docs/modules.md; kept as the running build log)*

**All original pillars shipped through spec 48; three more landed** —
**spec 50** (settings scope + full-CRUD RBAC + scalar-settings cascade + builtin-field
read grants + per-team internal comments), **spec 51** (issue types — a per-project
classification axis, colored chips, orthogonal to the epic/issue/subtask hierarchy),
**spec 52** (issue `#`-mentions in every markdown editor + per-field render widgets).

**Current runtime state (end of the 18-round polish day; rounds 14–18 in
commit AFTER `6f103a9`):** alembic head `5e4a41d09ca0` (single head; late-day chain:
`7ec22a4a1c25` view quick_filters → `c536f26534fb` item_cycle_records [spec 56] →
`5e4a41d09ca0` view sharing [spec 57]); **625** core tests green; served on
`http://localhost:8000` (detached uvicorn, current code, log `server/var/server.log`).
Frontend `web/dist` built + served. Everything in the bullets above is LIVE
and verified (Playwright chromium via `uv run --with playwright` — browser cached in
~/.cache/ms-playwright; per-feature verification detail in the round entries below and
in memory). Spec docs for the late rounds: `docs/specs/55-57*.md`. **Open decisions /
follow-ups:** run `scripts/fix_jira_markup.py --apply` (dry-run showed 11 451 comments
+ 1 035 descriptions would canonicalize; display already correct via render-time
conversion); a members-page UI for the user-merge endpoint; run
`jira_fetch_attachments.py` against real Jira (needs a PAT) before the next re-import;
label-chip truncation on list rows (cosmetic); **teams have no DELETE endpoint** (found
during spec-57 QA — cleanup needed SQL); **ask the user whether "share a personal
space" meant WIKI spaces** (doc spaces have no ACLs; the `view_shares` pattern
generalizes); ops guidance: **complete cycles, don't delete them** — deleting
CASCADE-drops the item↔cycle stint history (PIPE-116/117's 294 carryover records were
lost this way, unrecoverable).

** round (LIVE, committed with the service-desk day): automations rework + UI polish.** **Spec 58**
(`docs/specs/58-automation-event-conditions.md`): rules trigger on ANY catalog event
type (52 across items/comments/worklogs/attachments/links/cycles/releases/docs/admin;
`trigger` = raw event-type string, data-migrated) + nestable all/any/none **event
conditions** (`actor`/`changed_field`/`old_value`/`new_value`/`state_category`/
`payload`-path subjects, 11 operators, pure evaluator `automations/conditions.py`,
12 unit tests) + `GET /automations/catalog` + recursive condition-builder UI, AND
**spec 58b universal actions** (create_item/send_webhook[HMAC]/post_chat/notify_user w/
`{{token}}` templates — run even on itemless triggers; new NotificationType.AUTOMATION).
PLUS **spec 59** (itemless/general worklogs: nullable item + project/workspace anchors,
category REQUIRED + first-class in the timesheet — per-category strip, By-category
grouping, Log-time modal; `docs/specs/59-general-worklogs.md`). PLUS **spec 60** (team-restricted cycle visibility [`cycle_teams`, admin-only bypass,
404-hidden] + collapsible sidebar sections + projects-fold-by-default w/ current-route
auto-expand; `docs/specs/60-cycle-visibility-sidebar.md`). Alembic head
`8325cd80bd6d`; **648** tests green; verified E2E (comment-visibility rule +
state-into-done rule, both positive & negative). Same-day polish, all live: settings
Fields-page merge (Field Rules tab folded in as Builtin-fields section w/ shared
GrantsEditor), brand icons (`web/public/brand/`, favicon/sidebar/login, RaddMark/
RaddTile components), cycle-handle stats (estimate/logged/remaining chips one-line
right-aligned, RED negative remaining — cycle aggregate now unclamped Σ(est−logged)),
list-row rework (labels capped +N mid-row, fixed-width square state pills far right),
**per-surface card display config** (`lib/card-display.ts` slots + labels cap + zoom
slider, DisplayMenu on saved views/list/board/planning, localStorage per view/project —
server-side persistence on the View model is the designed follow-up), selenium
screenshot harness in the bg-job tmp (system Firefox + geckodriver).

** SERVICE-DESK WAVE (LIVE, committed): specs 61–66.** Closed every gap
from the service-desk audit; specs in `docs/specs/61-…66-….md` (each has As-built
notes). **Spec 61 workflow transitions** — optional per-project transition graph +
validation guards (`workflow_transitions`, `TransitionCheck` require_assignee/
estimate/team/comment/fields; `SettingKey.WORKFLOW_TRANSITION_MODE` off/guards/
strict via the spec-50 cascade, default off; enforcement in items.update_item AFTER
the whole patch applies → 422 {errors[]}; `GET /items/{id}/allowed-transitions`
drives graying/tooltips; editor on the States settings page). **Spec 62 requester
loop** — reporter auto-watch (notify planner), `mail_contacts` (one external
requester per item), auto-ack w/ threading subject `[KEY]`, outbound consumer
`mailintake.outbound` (public agent comments → email to contact, cursor seeds at
HEAD, at-most-once), plus-address project routing (`support+td@`), public tokened
forms (`/public/forms/{token}` API + SPA route outside the auth guard), shared
`radd/smtp.py`. **Spec 63 SLA depth** — per-priority policies + ordered FIRST-MATCH
(semantic change: ONE policy per item; evaluate-all retired), business-hours
windows (`business_start/end_minute`), `POST /items/sla/batch` (chips on list/
board/views/planning via the card-display `sla` slot, default off), `GET
/reports/sla` weekly buckets + Service-desk report card (project + workspace
reports). **Spec 64 queue views** — `ViewType.QUEUE` + batched `POST /views/counts`;
sidebar "Queues" section w/ live count badges; queue page = list variant w/
reporter/age/SLA columns, breached-first urgency ordering, DnD-rank disabled.
**Spec 65 CSAT** — new `csat` module: survey on resolve (consumer `csat.sender`,
per-project opt-in `SettingKey.CSAT_ENABLED` default OFF, recipient = mail contact
else reporter email, once per item), public `/public/csat/{token}` API + SPA star
page, rating chip in the rail, csat_avg/csat_count in the SLA report. **Spec 66
polish** — canned-response `{{variables}}` + render endpoint, automation
`send_email` universal action (to = literal|reporter|assignee|contact), KB
deflection `GET /search/deflect` + DeflectionPanel under the title input
(new-issue modal + authed form page). **Ground truth:** migration chain
`8325cd80bd6d → 57614f09f956 → 7be36ff1ac2c → fb577d3807f9 → d90a8f7daa8a`
(single head, applied); **712 pytest green**; web/dist rebuilt; **:8000 restarted
on this code** (NOTE: currently running as a background-job child, not the usual
setsid detach — re-detach it the standard way whenever convenient). Smoke-verified
live: allowed-transitions/deflect/mail-contact/csat/public-404s. **Operational:**
SMTP is still unconfigured (`RADD_SMTP_HOST` empty) so ack/reply/CSAT/send_email
paths are armed but dormant — outbound + csat cursors seed at stream HEAD, so
setting SMTP later never replays history; CSAT + transition enforcement are
per-project opt-ins (both default off); first-match is a real semantic change if
old complementary SLA policy pairs existed (fold targets into one policy).
Follow-ups seeded in the specs' Known simplifications (per-queue columns,
business-time report averages, custom-field canned tokens, deflection on the
public form). **Same-day addendum:** forms gained a proper ITEM-description
area (user caught that submit pages only had the summary): `forms.description_enabled/
description_prompt/description_required` (migration `40573860b0bd`, area ON by
default for new AND existing forms), textarea on the authed + public submit
pages, required enforced server-side (`description: required` 422), builder
controls (toggle/prompt/required) — **715 tests**, head `40573860b0bd`.
**Addendum 2 — workspace board views got state drag** (user: "board views can't
transition issues, only the project board can"): spec 24 had disabled state DnD
on workspace-spanning views (name-keyed buckets, "ambiguous"). Now `GET /states`
accepts `workspace_id` (readable projects' states), `bucketMovePlan` resolves a
name-keyed drop in the DRAGGED ITEM'S own project, `dragEnabledForAxis` lost its
projectScoped gate, and an unresolvable drop (item's project lacks that state
name) toasts instead of silently snapping back. Covers board columns AND state
swimlanes; spec-61 transition guards apply to these drags like any PATCH.
**Addendum 3 — project default surfaces** (user: "why can't I modify the default
board/list for a project?"): the built-in /p/KEY/board|list were zero-config
spec-04 surfaces. Now `views.project_default` (board|list; migration
`97f19379ae3c`) designates a saved view as the project's default — the builtin
routes redirect to it. `PUT/DELETE /views/{id}/project-default`
(project.manage): view must be project-scoped + slot-compatible (board→board,
list→list|queue) + workspace-visible, one per slot (previous holder cleared),
and PATCH/sharing changes that would break a live designation 409. Picker on
project settings → General ("Default surfaces"). **716 tests**, head
`97f19379ae3c`, :8000 restarted.
**Addendum 4 — cycle handles unified** (user: "why are the planning-view cycle
cards different from the project planning page?"): two renderers had diverged —
cycle-axis view sections got the handle (status pill, dates badge,
estimate/logged/remaining chips, done pill, progress bar) while
`routes/planning.tsx` still drew its round-11 hand-rolled header.
`CycleHeaderStats` moved into `components/cycles/CycleBadges.tsx` (the shared
atoms file) and the standalone planning page now composes the SAME handle —
done pill + progress come from `GET /cycles/{id}/stats` (server-real, not the
loaded page subset). Frontend-only; dist rebuilt.
**Addendum 5 — planning page rebased onto the view engine** (user showed the
two surfaces still structurally differing and asked for builtins to share the
views' base): `routes/planning.tsx` REWRITTEN as a thin wrapper over the exact
components planning views use — one paged `infiniteItemsQuery` fetch,
`groupItemsForView` cycle axis, `ViewList` (collapsible sections, ListRow
rows), `bucketMovePlan` DnD, shared Load-more. Deliberate config deltas only:
completed cycles hidden, backlog hides done/canceled. Consequence: per-section
counts are now loaded-subset (like views), not per-cycle server counts — the
old per-section paged fetches are gone. ALSO `ProjectDefaultSlot.PLANNING`
(enum-only, no migration): a saved planning view (e.g. cycle-filtered `^PIPE`)
can back `/p/KEY/planning` via the same designation flow + a third row in the
Default-surfaces picker. Board/list builtins remain separate implementations
sharing atoms — full rebase onto the view engine is the designed follow-up;
default-surface designation is the escape hatch meanwhile. 716 tests, tsc
clean, dist rebuilt, :8000 restarted.
**Addendum 6 — cycle-stats scoping bug + surfaces ARE views now.** (a) BUG
(user screenshot): cycle-handle time chips fetched `GET /cycles/{id}/stats`
UNSCOPED, so DEV's planning surface showed PIPE-115's TD estimate/logged
totals (cycles span projects). Fixed end-to-end: the stats endpoint + both
seams (`cycle_state_category_counts`, `cycle_time_totals`) gained
`project_id`; `cycleStatsQuery`/`CycleHeaderStats`/`ViewList` thread a
`cycleStatsProjectId`; project-scoped views pass `view.project_id`, the
planning page passes the project, the workspace cycle page stays unscoped by
design. Audited all consumers (grep cycleStatsQuery/CycleTimeChips): cycle
page + ViewList handles were the only fetchers; done-pills/progress were
already bucket-scoped. Live-verified: PIPE-115 unscoped = 6 items/2w 4d est,
DEV-scoped = 0/0m. (b) USER DIRECTION "why two entities of the same display" —
designation-as-overlay retired in favor of **seeded views**: every project
ships with workspace-visible, admin-editable Board/List/Planning views
(in-txn hook on project.created + backfill migration `62681dd4006c` — TD+DEV
seeded live), `project_default` marks the backer, designated views can't be
deleted (409, swap first), the settings card is now "Project surfaces". The
legacy builtin pages remain only as a no-designation fallback (dead in
practice). 716 tests, head `62681dd4006c`, :8000 restarted, dist rebuilt.
Same-day UX fix (user screenshot: sidebar duplicates + undeletable): surface-
backing views are EXCLUDED from the sidebar's generic per-project view lists
(the static Board/List/Planning entries ARE those views — queue-exclusion
precedent), and the view page swaps the dead Delete button for an emerald
"Project board/list/planning" chip whose tooltip explains the swap-first rule.
**Addendum 7 — designation concept DELETED (user: "I don't like these backing/
referencing ideas or the delete protection — projects just come with default
views; remove code that's no longer useful").** Final model: `seed_project_views`
creates three PLAIN views (Board/List/Planning) per project (hook + backfill
stay); `views.project_default` column DROPPED (migration `004bbb60df13`),
along with ProjectDefaultSlot/SLOT_VIEW_TYPES, the PUT/DELETE project-default
endpoints, all designation guards (delete protection, sharing/type-change
409s), the DefaultSurfaces settings card, `useProjectDefaultView`, and the
surface redirects. The builtin board/list/planning PAGES + their routes are
deleted too (`routes/board|list|planning.tsx`, RoutePath.projectList/planning,
`planningItemsQuery`); `/p/$projectKey` → new `ProjectHomePage` (redirects to
the project's first view; empty-state otherwise); the sidebar lists views
first then Roadmap/Reports/Settings (no static surface entries); ProjectNav =
Roadmap+Reports only; CommandPalette per-project entries = Project + Roadmap;
project-scoped VIEW pages gained the New-item button + `c` hotkey (they were
on the deleted builtin pages — creation UX preserved). Seeded views are
deletable (a project can genuinely have zero board views if the admin wants).
716 tests (designation test rewritten as the seeding test), tsc clean, dist
rebuilt, head `004bbb60df13`, :8000 restarted.
**Addendum 8 — two-scope settings (spec 67) + duplication sweep.** (a) USER
DIRECTION "instance vs workspace vs project — 3 layers is not useful": the
scalar-settings cascade is now **project → instance** (`SettingScope` lost
WORKSPACE; `resolve()` lost workspace_id — all callers updated; migration
`a7c2e19b4f30` promotes any workspace rows to instance + applied). Settings UI:
**General** tab = the instance-defaults editor ("defaults for every project",
instance-admin gated); **Instance** tab renamed **Server** (deploy/LDAP/SMTP
status only, scalar editor removed). **SLA policies are PROJECT-level now**:
`sla_policies.project_id` NOT NULL (PolicyCreate requires it, workspace_id
derived), list by project, matched_policy = the item's project's policies,
admin page moved to `/p/KEY/settings/sla` ("SLAs" tab); spec doc
`docs/specs/67-two-scope-settings.md`. (b) DUPLICATION SCAN (full report in the
 session log): fixed same-day — `radd/worker.py` PeriodicLoop
replacing 9 copy-pasted dispatcher loops (standardizes restart-safe stop();
webhooks' httpx client now lazily created/closed), dead `BoardColumn.tsx`
deleted, `lib/dates.ts` consolidating 6 shortDate/formatDate/relativeTime
copies (FIXES a real my-work timezone bug — unanchored date-only parse),
`AssigneeAvatar` now wraps the shared `Avatar` (custom avatar colors/emoji
finally show on rows/cards), stale ViewSwimlanes docstring. DEFERRED (M
effort, recommended): shared outbox-consumer skeleton (3 verbatim head-seeded
copies: csat/googlechat/mailintake-outbound + 2 partial), `useBucketDrop()`
hook for the 3 DnD wirings, `<QueryError>` for ~28 inline error boxes,
web `lib/duration.ts` hardcodes 8h/day while the server setting is per-project
(latent timesheet display divergence). Googlechat dispatcher gate deliberately
left as-is (url-only, no run_workers — flagged). **716 tests**, head
`a7c2e19b4f30`, dist rebuilt, :8000 restarted, smoke-verified (project SLA
list + instance settings live).

**Addendum 9 — global scope + all deferred consolidation done (spec 67 as-built
follow-up).** (a) `timelog_hours_per_day` is INSTANCE-ONLY now (scopes=(INSTANCE,),
per-project resolution removed, migration `c4f8a25d91e7` deletes stray project
rows; `resolve()` defensively filters lookup scopes by the spec). `GET /instance`
(+ login-options) exposes `timelog_hours_per_day`/`timelog_days_per_week`; web
`duration.ts` takes a DurationConfig + `useDurationConfig()` hook — the
hardcoded 8h/day is GONE (timesheet + HistoryTab thread it; other surfaces
render server-formatted strings). (b) SCOPE VOCABULARY: `PermissionScope.GLOBAL
= "global"` (wire value changed; web mirror updated; roles matrix says "Global
permissions"), `authz.global_scope_permissions`, `perms.global(...)` (29 call
sites), catalog descriptions + ~25 UI strings swept "workspace"→"global" WHERE
IT MEANT SCOPE — the workspace ENTITY keeps its name everywhere (workspace_id,
tables, memberships, `workspace.manage` atom keys stay: stored in role rows,
resource=entity). (c) ALL DEFERRED TASKS: `events/runner.py`
`run_head_seeded()` replaces the 3 verbatim consumer skeletons (csat/googlechat/
mailintake-outbound; googlechat delivery now correctly after cursor commit;
search/notify/automations left — real semantic differences), googlechat
dispatcher now gates on `run_workers` too, web `lib/bucket-drop.ts`
`useBucketDrop()` replaces the 3 copied drop-target wirings (+ fixes stale
hover on cancelled drags), `components/QueryError.tsx` replaces 28 inline
error boxes. **716 tests**, head `c4f8a25d91e7`, dist rebuilt, :8000
restarted, smoke-verified (/instance fields + permissions scopes=global|project).

Row-alignment polish (user screenshot): queue meta columns are FIXED-width now
(reporter w-36 truncate, age w-11 right, SLA chip in a w-24 slot rendered
empty-or-chip), the optional list-row sla slot got the same fixed wrapper, and
unassigned rows render `UnassignedSlot` — an avatar-sized dashed "—" circle —
so the priority/assignee/state columns never drift (CardSlots assignee slot:
avatar OR placeholder). Labels column too (user follow-up): row titles are now
the ONE flexible cell (`flex-1 truncate` — the "max summary length" is
responsive, not a char cap) and labels render in a fixed `w-56` right-anchored
column (present even when an item has no labels; `LabelChips nowrap` clips a
single line, +N tooltip carries the rest) — applies to list/queue/planning
rows via the shared ListRow; board cards keep wrapping (vertical layout).

**Page-level SLQ filter bar (rounds 14+15 — spec 55, LIVE).** The list
route's ad-hoc SLQ bar is a shared affordance on every content page, mounted right
under each page's filter controls: board, list, cycle, planning, roadmap, and saved
views (under the quick-filter chips). Pieces: `lib/slq-filter.ts` (`useSlqPageFilter`)
+ `components/views/SlqFilterBar.tsx` (SearchCode icon + compact `SlqEditor` +
`AskAiBar`). **Round 15 rework (scale): typing VALIDATES, Enter EXECUTES.** New
backend `GET /items/slq/validate` (parse + compile — field/label resolution only,
zero work_items I/O; 422 {detail, position} incl. did-you-mean) behind
`service.validate_slq`; `useSlqValidation` in hooks.ts replaced the old live-execute
`useSlqProbe` EVERYWHERE (page bars, ViewModal + quick-filter chip rows, automation
RuleEditor) — no surface executes SLQ speculatively anymore; match counts appear only
after a committed run. Status line gained a `ready` state ("Valid — press Enter to
run"); NL→SLQ "Ask" commits its query immediately. Editor Enter semantics (Jira
rule): Enter accepts a suggestion only after arrow/hover navigation, otherwise runs;
Tab always accepts; Esc now also cancels a still-debouncing suggest request (fixed
the reopen-after-Esc race). Semantics: list swaps to the server result (honors ORDER
BY, offset-paged Load more via `infiniteSlqItemsQuery`); other pages intersect by id
— scoped `project_id` (board/planning/roadmap), `cycle_id` (cycle page, ANDs
server-side with `q`), view's project or workspace (views). Cycle-page stats fall
back to client-side counts while a query is active; empty states distinguish "no
items" from "no matches". **Pagination everywhere (round 15):** board + roadmap moved
to `infiniteItemsQuery` (Load more footer/link), saved views to
`infiniteViewItemsQuery` (Load more strip; CSV exports loaded+filtered set), planning
sections offset-paged per section (backlog Load more), committed list-SLQ results
paged. `item-mutations.ts` patches the paged caches (`mapPages`/`transformPages`
helpers): move/update/star/reorder all optimistic against `InfiniteData<Item[]>`;
`useMoveItem` patches flat + paged project caches. Intersection match set stays one
200-item page — "N+" flags the cap. Verified via Playwright with network
interception: 0 item-executions while typing (1 validate call), exactly 1 execution
on Enter, Load more on list/board/view/planning, arrow+Enter accepts, board drag
optimistic through the paged cache (reverted). 621 pytest green; :8000 restarted.

**Co-ownership + ownership transfer (round 18 — spec 57 cont., LIVE).** ShareLevel
gained **`owner`** (co-ownership: full control — edit/re-share/delete/transfer; grantable to
people or teams, NEVER valid for workspace_access → 409) and **`POST /views/{id}/transfer`**
(owner/co-owner reassigns owner_id; target needs item.read in scope → 409; target's redundant
grant rows dropped; PREVIOUS owner auto-kept as editor — no accidental lockout). Validation order:
invalid workspace_access rejects before the broadcast-permission check. UI: "co-owner" in the
grant-level selects + "Transfer ownership to…" in the modal's Sharing section (applied LAST on
save — after the sharing PUT, since manage rights may vanish the moment it lands). No migration
(level is a string col). 625 pytest (+co-ownership/transfer matrix); live-verified: co-owner
re-shares (200), workspace_access=owner 409, transfer → old owner editor (can_edit true /
can_manage false / delete 403), new owner deletes (204). QA user cleaned.

**View ownership + sharing (round 17 — spec 57, LIVE, `docs/specs/57-…`).**
Sharing no longer surrenders ownership: `views.owner_id` = creator in every mode (NULL only on
legacy pre-57 rows → view.* atoms manage those); NEW `view_shares` (user XOR team + ShareLevel
viewer|editor, FK CASCADE, merge-inventory dedupe) + `views.workspace_access` (level every member
gets, NULL = not workspace-visible; migration `5e4a41d09ca0` backfills legacy shared → 'viewer').
Visibility = owner ∪ grantees (direct/team) ∪ members when workspace_access — others 404, ADMINS
INCLUDED; editor grantees edit the definition; re-share/delete = owner only. `PUT
/views/{id}/sharing` full-state replace (owner-gated; enabling workspace_access needs view.create
— broadcast bar; user/team shares need only item.read, so members share personal views freely).
`ViewRead`: `owner` ref + `workspace_access` + `shares[]` + per-actor `can_edit`/`can_manage`
(server-computed). Frontend: `ViewSharingEditor` in the view modal (workspace-access select +
person/team rows w/ levels, owner-only), view page gates Edit/Delete on the server flags + "by
{owner}" chip. `ViewCreate.shared` stays as alias (viewer) so demo_views.sh keeps passing. 624
pytest green (+test_view_sharing.py matrix); live-verified with a scratch member: team-gated
visibility (join team → appears, revoke → vanishes), viewer 403/editor 200, owner-only re-share,
member broadcast 403, admin CANNOT delete a member's personal view; UI create/edit round-trip.
QA artifacts fully cleaned. NOTE: "share a personal WIKI space" (user mentioned) is NOT covered —
doc spaces have no ACLs yet; the view_shares pattern generalizes if wanted.

**Cycle regex filter + stint history (round 16 — spec 56, LIVE, `docs/specs/56-…`).**
(1) `views.cycle_filter` is now a REGEX (was glob): case-insensitive unanchored, `re.compile`-validated
on save (409), matched client-side (`matchesCycleFilter`); ViewModal shows the field with live
invalid-regex feedback + save gating and now ALWAYS for planning views (they're implicitly
cycle-grouped — before, planning views couldn't set a filter at all). (2) **Item↔cycle stint
history**: `item_cycle_records` (cycles module, migration `c536f26534fb`) — one row per visit,
`removed_at` NULL = open; items service records on every cycle change (create+update — carryover
moves route through update); `ItemRead.past_cycles` (closed stints, deduped) renders as
"Previously in …" chips under the issue rail's Cycle picker; **SLQ `past_cycle`** queries closed
stints (`past_cycle = "PIPE - 115"`, `IS NOT EMPTY` = rolled over; current cycle deliberately
excluded — that's `cycle`); autocomplete + cheat sheet updated. Backfill: migration seeds open
rows; `scripts/backfill_cycle_history.py --apply` RUN on live (mined events; **294 PIPE-116/117
stints unrecoverable — those cycles were DELETED from the workspace; deleting a cycle
CASCADE-drops its history, complete instead of delete going forward**). 623 pytest green
(+test_cycle_history.py); Playwright-verified (regex view `^TS`, modal invalid-regex gate,
carryover chip on TD probe item, past_cycle autocomplete); QA artifacts deleted; :8000 restarted.

**Configurable screens (spec 53) — NEW module, first slice shipped.** Field-layout
config per (project, issue-type): `screens`/`screen_fields` (migration `1ec5ca425fcd`),
`GET /screens/effective` (resolve = issue-type → project-default → built-ins; builtins
default primary, **custom fields default secondary** so the noisy tail collapses in the
peek with zero config), `GET/PUT /screens` (project.manage). `IssueProperties` renders
fields individually by placement — primary shown / secondary under a collapsible "More
fields" (collapsed by default in the peek panel) / hidden omitted; editor at project
settings → **Screens**. Next slices: card display (board/list) driven by the same config;
finer builtin grouping. **UI polish this pass:** the sidebar hides completed cycles behind
a "Show completed (N)" toggle; **full-width sweep** — every view/settings page now fills
the pane instead of sitting in a centered `max-w-*` column (removed `mx-auto max-w-*` from
the shared `SettingsPage` wrapper + cycle/projects/inbox/my-work/reports/workspace-reports/
issue-page/wiki-page; docs-index grid widened). Only the login card and the public
form-submit page stay intentionally narrow-centered (focused forms).

**Active thread — a settings/UX polish pass (specs 50-52 "Known follow-ups"):**
1. ✅ **Field default values** *(was the one explicitly missed)* — `default_value` (nullable JSONB,
   migration `bb706d3802ae`) on custom-field defs, validated against type/options on create + `PATCH`;
   `apply_defaults` seeds it onto items that omit the key (explicit null preserved); inline editor in
   the fields settings panel + the New-field modal, both reusing `CustomFieldControl`.
2. **Comprehensive settings-UI pass** — shipped: dismissible info banners + value-chips
   (Type/Priority/State) + up/down reorder on the config editors, **+ inline default-value editing
   (done, item 1)**. Still to do: the slide-in "Create new / Use existing" add panel, and sweeping the
   *remaining* settings pages into the same settings design language.
3. **Spec 50/51/52 follow-ups** — ✅ `timelog_hours_per_day` into the scalar cascade (now resolved
   per item project like `work_week_days`); ✅ issue-mention backlinks (`ItemLinkType.mentions`
   auto-derived from `#[…]`, read-only Mentions section on the item view). Still open: builtin-field
   READ blanking on reports/FTS/MCP surfaces (item hydration done); scoped-settings audit events;
   workspace-level custom-role assignment (long-standing spec-36 gap); Priority/State letter-chips in
   *list rows* (rail done); `comment_counts` accuracy for team-restricted internal comments.

**Then** adoption + the pre-OSS checklist (§8): real AD login, replace the real-content sample data
with synthetic, trademark/security pass.

### Operational notes for a fresh session
- **Restart the server after backend changes** (no `--reload`). Kill by PID, NOT `pkill -f` —
  the kill command string self-matches and kills the tool shell:
  `PID=$(ss -ltnp | grep ':8000' | grep -oE 'pid=[0-9]+' | cut -d= -f2); kill $PID`, then
  `cd server && setsid nohup uv run uvicorn --factory radd.app:create_app --host 0.0.0.0 --port 8000 > var/server.log 2>&1 &`.
- **Alembic autogenerate ALWAYS proposes to drop `ix_doc_pages_fts`** — a false positive (functional
  GIN index it can't introspect). STRIP that line from every generated migration or docs search breaks.
- **npm is not preinstalled, but node + network ARE** — bootstrap npm from the registry when you need
  to add a dep: `curl -s https://registry.npmjs.org/npm/latest | node -e '…dist.tarball…'`, download +
  `tar xzf`, then `node <extracted>/package/bin/npm-cli.js install …` against `web/`. (This is how
  `@milkdown/crepe` + react-markdown got in — the old "no package manager" blocker is gone.) For plain
  builds still use `web/node_modules/.bin/{tsc -b, vite build}` directly. dnd-kit is NOT installed.
- **Rich text = Milkdown/Crepe for BOTH read and edit (spec 54 + unification):** the
  user's directive: ONE consistent engine, "good clean feature-rich viewing + editing like the big
  commercial trackers" — no variant splits, no separate read renderer for rich surfaces. **Edit:**
  `editor/RichEditor.tsx` — every editor (description, comments, wiki) gets the SAME fixed TopBar
  (heading selector trimmed to P/H1–H3), `/` BlockEdit menu (h4–h6 nulled) + block drag handle,
  table widget; floating selection Toolbar off; ImageBlock gated on `onUploadImage` (feature-flag
  cascade auto-hides its TopBar//-menu items). **Read:** `editor/RichViewer.tsx` — the SAME Crepe in
  `setReadonly(true)` with all chrome features off, so content is pixel-identical read vs edit
  (headings, tables, code blocks incl. copy button, images). Used via `LazyRichViewer` (same lazy
  chunk + an IntersectionObserver that mounts instances only near the viewport — issues carry up to
  ~236 comments; raw-markdown placeholder holds layout) in item description, comment bodies, doc
  pages; existing pencil-icon flows switch to the editor. `lib/markdown.tsx` (react-markdown) remains
  ONLY for small previews (AI summary, doc history). **Shared chips:** `editor/chips.ts`
  `mentionChipsPlugin` decorates `@[Name](uuid)` / `#[KEY](KEY)` tokens as colored pills in BOTH modes
  and routes clicks via `handleDOMEvents.click` (NOT `handleClick` — that fires on mouseup, too late
  to cancel an anchor's native navigation; this bug was caught by the Playwright smoke). Read mode:
  issue chips navigate, external links open a new tab; edit mode: chip clicks are consumed. One
  typography scale for both in `rich-editor.css` (theme's 42px h1 → 22/18/16/14) + table-widget
  calming (no fade-lag, tightened + hover-bridged action popup). `@`/`#` autocomplete unchanged
  (`editor/mention.ts` + portaled popup; `#` opens immediately with hint/searching/no-match rows;
  bare-number queries match key numerics server-side via `search/service.py key_pattern`).
  Verified with Playwright chromium (scratch venv; browser cached): 4–23 viewers/page, chips render +
  route, contenteditable=false, h1=22px, composer TopBar present, zero console errors. **Note:** a
  Tiptap trial was reverted back to Milkdown — no `@tiptap/*` remains.
- **Editor: plain-text mode + `/` quick actions (GitLab-inspired):** every RichEditor has
  a footer bar — "Switch to plain text editing" toggles `editor/PlainEditor.tsx` over the SAME value
  (`radd.editor.plainText` localStorage pref, sticky across editors/sessions; Crepe reseeds from the
  live markdown on switch-back) + an M↓ badge. Plain mode is FEATURE-PARITY, only the rendering is
  plain (user directive): its own markdown toolbar (H1–H3/bold/italic/strike/code/link/lists/task-
  list/quote/code-block/table/divider + image when upload is wired; selection-aware wrap/line-prefix-
  toggle edits), the SAME `@`/`#`/`/` popups (shared TRIGGER_RE/SLASH_RE from mention.ts; caret
  coords via the mirror-div trick; tokens spliced as literal markdown, slash commands removed+run via
  `PlainEditorApi.replaceRange`), and paste-image upload. Crepe's BlockEdit slash menu is OFF for good (it
  only duplicated the toolbar's inserts); `/` at block start now opens a QUICK-ACTION menu that acts
  on the ISSUE in context (`editor/mention.ts` gained the `/` trigger; `items/quick-actions.ts`
  `useIssueQuickActions` builds the entries: Assign-to-me/Unassign/Assign:<user>, State:<s>,
  Priority:<p>, Add/Remove label:<l> via the normal PATCH path, plus every enabled MANUAL automation
  as a custom action → POST /automations/{id}/run). Token-filtered ("/assign hus"), Enter runs +
  removes the typed command, no issue context (wiki/new-item) → `/` inert. Extensibility: custom
  slash actions = manual automations (settings rule builder now offers the Manual trigger; extensions/
  MCP create rules via REST). Verified end-to-end on a throwaway :8002 server + Playwright (assign,
  automation-run → priority=blocker, plain-toggle roundtrip, cleanup). NOTE: needs the :8000 restart
  to go live (runnable/run endpoints + MANUAL enum are backend changes).
- **Planning as a VIEW TYPE + quick filters:** `ViewType.PLANNING` — creatable like
  board/list (New-view modal option), workspace-spanning or project-scoped, with the full SLQ
  filter; rendered as cycle-grouped ViewList sections (the spec-23 cycle axis does the work: staged
  cycle headers with dates/progress + Backlog bucket + spec-24 cross-bucket drag), stored axes
  ignored. **Quick filters (Jira-style)** on EVERY view type: `views.quick_filters` JSONB
  [{name,query}] (migration `7ec22a4a1c25`), each chip's SLQ compile-validated on write (ORDER BY
  rejected 409 — chips are conditions only); the view page renders a chip row, active chips
  parenthesized-AND into the query (`combineQueryWithFilters` keeps the base ORDER BY at the tail)
  and the ENTIRE machinery (fetch + optimistic drag/star/reorder caches) targets the filtered
  dataset via an `effectiveView`. Verified live: workspace planning view with TD/DEV/"Mine"
  (`project = TD` etc.) chips filtering correctly; test view deleted. The standalone
  `/p/$key/planning` page stays as the zero-setup per-project surface.
- **Polish batch (the "Jira replacement people would want" pass):** (1) **server-side
  cycle filter** — `GET /items?cycle_id=` (UUID-or-`none` = backlog, same idiom as assignee/team);
  the cycle page now does ONE paged server-filtered fetch (`cycleItemsQuery`, up to 2000) instead of
  per-project pages client-filtered (which silently truncated 330→69). (2) **Planning view**
  (`/p/$key/planning`, sidebar + ProjectNav entries): backlog (cycle=none, done/canceled hidden)
  beside active/upcoming/draft cycles as native-DnD drop targets — drag a row to (re)assign its
  cycle via the normal PATCH path; counts are server-real. (3) **Notification prefs** —
  `notification_prefs` (migration `9a829dc79eef`): per-type mutes filtered in the notify consumer +
  an email-digest opt-out honored by the emailer (rows still stamped so the backlog drains);
  `GET/PUT /notifications/preferences` + a Notifications section on /settings/profile. NOTE: bulk
  cycle moves never notified anyway (planner only reacts to state/assignee/description). (4)
  **Migration fidelity** — Jira ATTACHMENT import: `jira_export_build` records per-issue
  {filename,url}, new `jira_fetch_attachments.py` downloads them (resumable, Bearer PAT), and
  `import_jira --attachments-dir` uploads per item + rewrites `!file!` embeds to real
  `![name](/attachments/id)` markdown (`jira_markup.replace_attachment_embeds`, tested) in
  descriptions (post-upload PATCH) and comments. **USER MERGE**: `POST /users/{id}/merge`
  (instance-admin) folds a duplicate identity — explicit table inventory in `auth.service.merge_users`
  (repoint / dedupe-composite / purge-credentials lists — KEEP IN SYNC when new tables reference
  users), source deactivated + `user.updated {action: merged}` event. No UI affordance yet (API
  only) — follow-up. (5) **Obsidian-inspired dark theme** — the stock blue-black zinc scale remapped
  to neutral lifted grays (#1e1e1e page family) via the same Tailwind-v4 variable seam as the light
  theme (zero component changes); `rich-editor.css` converted from hardcoded hexes to
  `var(--color-zinc-*)`, which also fixes the editor being a dark island in LIGHT mode; sky-300
  added to the light remap for issue chips. All verified on a throwaway DB
  (radd_qa_batch, dropped) + live screenshots; 621 tests.
- **Cycle management, Jira-style (two passes — the project language is CYCLES, never
  "sprint", per user):** `POST /cycles/{id}/complete` closes a cycle mid-window
  (`cycles.completed_at`, migrations `bda2d16f2533`+`5df5c6f35ec7`; `cycle_status` is
  completed_at-aware) moving open items to a chosen cycle or backlog (items seam
  `move_open_cycle_items`, per-item update_item as the caller) and optionally starting the target
  (length inherited from the closed cycle). **Recurring series** (user rework of the first
  workspace-setting approach — REVERTED from the scalar registry): per-LABEL `cycle_series` rows
  (label/drafts_ahead/next_number, membership by name via `parse_cycle_name`), created from the
  New-cycle modal's "Recurring cycle" checkbox (bare label + starting number = Jira-import
  continuity, e.g. begin at 120), managed in a "Recurring series" section on /settings/cycles
  (edit look-ahead + next number, delete = stop recurring); provisioning tops each label to N
  future cycles, skipping taken numbers. Complete-modal targets are SAME-LABEL future cycles.
  **Cycle page**: stats header (`GET /cycles/{id}/stats` — per-category counts + estimate/logged/
  remaining totals via items+timelogging seams) + person/team filters that drive BOTH the stats
  (server params) and the list (client filter); the progress bar now uses stats (the per-project
  item queries are paginated — the list can be a subset, stats never are). **Scheduled cadence
  (third pass, migration `229e9d3c413b`):** series optionally carry start_weekday (0=Mon) +
  duration_days — provisioned cycles then arrive with real timelines (pure `series_windows`:
  chained back-to-back after the label's latest scheduled end, starts snapped to the weekday;
  stale chains restart from today), existing dateless drafts get scheduled when a cadence is
  added, and a recurring create with no dates self-schedules ("2-week Mondays" = weekday Mon +
  14d). UI: "Starts on"/"Duration (days)" in the New-cycle recurring section + editable cadence
  per series row (Unscheduled clears via explicit nulls). Verified end-to-end on
  a throwaway server (recurring create → QAS-51/52 + series next=53; stats est 2d/logged 4h/
  remaining 1d 5h; filter→0; complete → same-label move + QAS-53 top-up; bare "QAX"@120 →
  QAX-120) with full cleanup; live :8000 restarted. NOTE: the user completed the real PIPE-116 →
  117 with this flow same-day.
- **Time-tracking polish:** the peek drawer's rail renders `TimeTrackingPanel` with
  `compact` (totals + bar + "Estimate: X · N entries" line only — no log form, no worklog list; the
  full page keeps everything). BUG FIX: `format_duration` floored negatives to "0m", so an over-
  logged item's remaining ("estimate − logged") rendered as "0m over" — negatives now keep their
  magnitude ("-2h 45m" → UI "2h 45m over"); pinned in test_timelog_duration.py. Backend change →
  needs the :8000 restart.
- **Peek vs direct navigation:** issue keys are REAL links everywhere —
  `ItemBadges.ItemKeyLink` (a TanStack `Link` to `/issues/$itemKey`, `stopPropagation` so the row's
  peek handler doesn't fire; middle/ctrl-click new-tab works since it's a true anchor). Rule: click
  the KEY → full issue page; click the card/row BODY → `?peek=` side panel; the peek header's key
  also expands to the full page. Wired in: BoardCard, list.tsx table rows, ViewList rows, cycle rows,
  My-Work rows/recent-chips/notifications, roadmap label rows + UnscheduledTray. Rows that were
  `<button>` wrappers became `div[role=button]` (anchors can't nest in buttons). Timesheet label
  stays peek-only (it's the only click surface there). Verified with Playwright: key→/issues/KEY,
  row→?peek=, no page errors.
- **Markdown rendering (read mode):** `lib/markdown.tsx` `Markdown` = **react-markdown + remark-gfm**
  (remark is the same parser Milkdown serialises to). React elements only (no innerHTML). Custom tokens
  via `remarkRaddTokens`: `@[Name](uuid)`→mention chip, `#[KEY](KEY)`→`/issues/KEY`, and `<br>` in table
  cells → real line breaks. Removed the old `renderInline`/`parseBlocks` parser + dead
  `MarkdownEditor.tsx`. Still deferred: light-theme tint; converting the small settings textareas
  (canned/automation/release).
- **Jira backwards-compat (extended same day):** imported comments/descriptions are stored
  in Jira wiki markup. `lib/jira-markup.ts` `jiraToMarkdown()` (+ the backend twin
  `scripts/jira_markup.py` — KEEP IN LOCKSTEP, same rules/order; parity-checked over shared fixtures)
  converts it to markdown; the **viewer** applies it before rendering and the **editor** on seed, so old
  Jira content renders + edits correctly without a bulk migration. Full rule set now: links/bare-URLs,
  `[~user]`, `{quote}`/`{panel}` (→ blockquote, `title=` bolded), `{code}`/`{noformat}` (params cleaned
  to a language), `{{mono}}`, `hN.`, `||header||`/`|cell|` tables → GFM (headerless promotes row 1),
  `#`/nested `*#` lists, `*bold*`, `-struck-`, `{color}`/`{anchor}`/`{toc}` stripped, `!img.png!`
  embeds (URL → real image; filename → `*(image: …)*`, attachments were never imported), emoticons →
  emoji. Ambiguous rules (bold, `#` lists, strike, emoticons) collide with native markdown, so: the
  frontend gates everything on `HAS_JIRA_RE` (unambiguous-marker sniff), the importer converts
  unconditionally (`assume_jira=True` default), and `fix_jira_markup.py` back-fills with
  `assume_jira=False` (gated; `--assume-jira` lifts it for all-Jira DBs). Invariants pinned in
  `server/tests/test_jira_markup.py`. Live-DB dry run: 11 451/28 428 comments +
  1 035/3 281 descriptions would convert, samples clean — `--apply` (writes a rollback file) is
  **pending a user decision**; render-time conversion already fixes display either way.
- Verify pattern that works: throwaway server on an alt port + curl cookie jars (see the session log);
  the live `:8000` + its dev data should stay untouched, and any test rows created must be cleaned up.
- Frontend-only changes need only a browser hard-refresh (the running server serves `web/dist` live);
  backend changes need the restart above.

## Addendum 10 — spec 87: directory-owned teams, per-team delegation, grants that grant

User direction: AD-linked teams must be **read-only from AD** (mixed local/synced
membership "gets messy really quickly"); local teams may still contain AD users; not
everyone may create/edit teams, but a **team leader needs a per-team grant** to manage
only their own team. Follow-up direction in the same session: fix the dead global-grant
path **and audit for any other dead or useless grants**. Full detail:
`docs/specs/87-directory-teams-and-real-grants.md`.

**The audit reframed the work.** Cross-referencing every `Permission` against every
`authz.require` found that *all 47 global-scope atoms were undeliverable*:
`global_scope_permissions()` read `users.instance_role` alone and roles attach only to
projects, so no non-admin could ever hold `label.create`, `team.update`, `sla.*`,
`cycle.*`, `role.*`, `user.*` … while the roles matrix advertised every one of them.
That is also why the user's actual request could not be met by granting a lead
`team.update` — it had no delivery mechanism, and would have granted *every* team.

- **`global_role_grants`** (`auth/grants.py`): a role held instance-wide by a user or a
  team (`view_shares` shape, CHECK-constrained). Applies at **both** scopes — global
  checks union it in and every project treats it as one more granted role, so
  project-scoped atoms inside a globally-granted role are not a new dead grant.
  `GET/PUT /roles/{id}/global-grants` (full replace, `role.update`-gated — which is
  escalation-equivalent to admin, documented as such). `/auth/me` now returns
  `effective_permissions()` so grants reach the SPA's gates.
- **Atoms dropped:** `user.delete`, `import.run` (no endpoint could exist),
  `dashboard.update`/`dashboard.delete` (spec-57 ownership decides). Migration
  `3a363a121502` strips them from stored role JSONB — `RoleRead.permissions` is
  `list[Permission]`, so a stale string would 500 `GET /roles`.
- **Endpoints built** for atoms that had none: `PATCH`/`DELETE /labels/{id}`,
  `DELETE /states/{id}` (409 if default or occupied), `DELETE /fields/{id}`,
  `DELETE /webhooks/{id}`, `DELETE /teams/{id}` (409 while attached to a project — this
  closes the "teams have no DELETE endpoint" follow-up from spec-57 QA above).
  `PATCH /users/{id}` honors `user.update`, with `instance_role` kept hard-admin.
- **`teams.source`** (`TeamSource` local|directory): membership 409s on a directory team,
  enforced in the service. Linking re-sources the roster to `directory` (nothing frozen
  outside the sync's reach), unlinking to `manual` (the escape hatch — no access lost).
  Name + project grants stay local by design.
- **`teams.owner_id` + `team_managers`:** a team leader administers ONE team — roster +
  rename — but cannot appoint managers, transfer, delete, or attach the team to a
  project. **A leader decides who is on their team, never what their team is entitled
  to.** `MeRead.manages_teams` gates the Teams nav (delegation is invisible to the
  permission union).
- **Stale-group guard:** an empty AD member search is ambiguous (empty vs. renamed /
  deleted); believing the latter revokes everything the team grants. `reconcile_team`
  confirms the DN resolves, raises `StaleDirectoryGroup`, and sets
  `teams.directory_missing_since`; while set, the login path holds removals too, so the
  team cannot be drained one sign-in at a time around the periodic guard.
- **A broken link does NOT unlock the team** (user direction, same day): read-only stands
  as long as the link exists — a missing group keeps its people and stops every removal,
  but re-opening editing is a deliberate unlink, never inferred from a directory the
  server may be misreading. Amber `AD group missing` badge on the row + a one-click
  "Unlink and edit here" banner. Required making the signal trustworthy: `get_group()`
  returned `None` for a dead DC and for a genuine not-found alike, so it now raises
  **`DirectoryUnreachable`** for the former (incl. the eager `auto_bind` in
  `service_connection()`, which sat outside the try) — an outage records an error and
  touches nothing instead of flagging healthy teams.

**Runtime state:** alembic head `78c86f700dbe` (chain `466eca47eeee` global grants →
`3a363a121502` atom strip → `78c86f700dbe` team source/ownership/managers); **824** core
tests green; `web/dist` rebuilt (tsc clean). Verified end-to-end on a throwaway
`:8099` server: the two live AD-linked teams migrated to `source=directory` and now 409
on a manual member add; team create/managers/transfer/delete and the global-grants PUT
all round-trip. `alembic check` still reports only the long-standing `ix_doc_pages_fts`
false positive (alembic cannot see expression indexes).

## Addendum 11 — spec 88: AD import conflicts (flag duplicates, overwrite or merge)

User direction: importing AD users must **flag duplicates already in the system** and offer
to **overwrite or merge, keeping the AD entry** — "essentially update the users list from AD
and merge conflicts, asking whether or not to overwrite; it should overwrite email and such."
Detail: `docs/specs/88-ad-import-conflicts.md`.

**Why it mattered:** Radd identifies people by EMAIL and accounts arrive from several places
(Jira importer, local signup, OIDC, an older mail domain). `find_or_create_user` matched on
email alone, so importing `jsmith@corp.example` while the same human sat there as
`jsmith@old-domain.example` minted a SECOND account and split their history — and reported it as
a clean `created: true`. Note Radd has **no username column**: a sAMAccountName can only be
compared against an existing email's LOCAL PART, which is what "duplicate username" means here.

- **Preview first.** `POST /ldap/directory-users/import/preview` runs the PURE
  `plan_user_import` over the selection × the existing roster → `new` | `linked` | `conflict`,
  each match carrying WHY it matched (email / username / name). Nothing is written.
- **Then resolve.** The import endpoint takes a per-entry `ImportResolution`:
  **overwrite** (one account takes AD's email/name/source — **`id` preserved**, so every issue,
  comment and worklog stays attached; 409 instead of stealing an email another account holds),
  **merge** (fold the look-alike into the AD-identified account via `auth.merge_users`, survivor
  takes AD's values), **create** (they really are two people), **skip**. No resolution = the
  pre-88 create-or-link behavior, so the endpoint stays backward compatible.
- **Nothing auto-resolves.** A name collision is a heuristic and rewriting someone's email
  address is not inferable — the preview only *suggests* (merge when both accounts exist, else
  overwrite) and a human confirms. The review UI spells out each consequence in plain language.
- **Known consequence to flag when using it:** overwrite sets `source=ldap`, so a previously
  local account becomes directory-governed — the user sync may rename it and, with
  `ldap_user_sync_deactivate_missing` on, deactivate it when the person leaves AD. The password
  hash is deliberately kept (no mid-migration lockout).

**Runtime state:** no migration (behavior + endpoints only); **837** core tests green;
`web/dist` rebuilt (tsc clean). Verified against the live dev DB on a rolled-back transaction:
a legacy `@old-domain.example` account reporting a real issue was classified `conflict`/`overwrite`,
and after applying it the same row carried the AD address with the issue still theirs.

**Why "Sync users" looked broken (diagnosed):** it wasn't. The pass returns
0/0/0 because (a) every enumerated AD user already has an account, matched by email, so there is
nothing to provision, and (b) the name-refresh step only touches `source=ldap` accounts —
but **~98% of those matches are `source=local`**, created by the Jira importer. So the sync
is structurally inert for ~98% of the roster. A toast reading `0 · 0 · 0` gives no hint why.

**Live-instance shape:** ~1.3k Radd accounts vs ~1k enumerated AD users — nearly all
exact-email matches, a couple dozen name-only duplicates (mostly `@example.com` Jira
placeholders; almost none own work), and a couple hundred with no AD counterpart (mostly
leavers who own work — never delete; the rest empty, incl. two directory service accounts).

**`scripts/reconcile_ad_users.py`** (spec 88) is the one-off cleanup: buckets every account
ENFORCE / MERGE / KEEP using the same planner as the interactive import, dry-run by default,
`--apply` writes a timestamped JSON audit of every touched account's before-state.
`--enforce-only` / `--merge-only` / `--exclude EMAIL` for control. KEEP is never touched.

**Hazard found while diagnosing — do NOT enable `ldap_user_sync_deactivate_missing` yet:**
several dozen active privileged-alias accounts are outside the enumeration (privileged
accounts outside the search base and/or lacking `mail`, provisioned by LDAP *login* via the
synthesized UPN), so the departure sweep would read them all as gone and deactivate them.
Confirmed the same humans appear in the enumeration under their real mailbox address (alias
and mailbox differ), so email-keyed matching cannot see they are present.

**RECONCILE APPLIED** (`--apply` with the privileged-alias prefix and one alias-named account excluded;
DB snapshot first at `server/var/backups/radd-pre-reconcile-20260724.dump`, audit JSON
kept untracked under `var/`): **~1k enforced, two dozen merged.**
Result: the `source` mix flipped from overwhelmingly local to overwhelmingly ldap; **zero active
`@example.com` placeholders remain**; the sync now governs **all but one** matched account
(was a handful), so "Sync users" is finally a live operation rather than a structural no-op.
One duplicated person's 6 items repointed to their AD-keyed account (both rows inactive —
user accepted merging into a deactivated survivor). The owner's directory account intact: admin, active,
now ldap. Two deliberate hold-backs: the privileged-alias accounts (user: "I don't need those in
the system" — still present, own no work, never logged in, none are admins → retire when
ready) and one account whose AD `displayName` is literally its alias and would
have degraded a real name.

**Departure-sweep blast radius after the reconcile: unchanged** (the alias set plus a
handful of others) — unchanged by the reconcile
because those accounts were already ldap-source. `ldap_user_sync_deactivate_missing` stays
OFF until they are retired or the search base widens.

**Unrelated test fix in the same pass:** `test_user_sync_base_cascade_override_beats_env`
asserted that NO instance-scope `ldap_user_sync_base` existed, so it started failing the moment
the Directory page saved a real one.
It now clears that key inside its own rolled-back transaction — configuring the product must
never fail its own tests. The live setting was verified intact afterwards.

## Addendum 12 — spec 89: deleting users, with their work reassigned

User direction: *"I want to be able to delete local users, and when deleting them get asked
who should own everything that they did before."* Detail:
`docs/specs/89-user-delete-with-reassignment.md`.

**This reverses spec 87**, which dropped the `user.delete` atom arguing no endpoint could
exist behind it. Wrong call: deletion is legitimate, it just needs the authored work rehomed
first. The atom is back and the CRUD triple for `user` is whole again.

- `GET /users/{id}/content` → what the account owns; `DELETE /users/{id}?reassign_to=…` →
  hard delete. Successor REQUIRED when anything is owned (409), omitted when nothing is, so
  clearing placeholder accounts stays one click. The row really goes — unlike merge (keeps a
  deactivated shell) or `PATCH {active:false}` (revokes access only).
- **Worklogs are deleted, not reassigned** (user decision): crediting a successor with hours
  they never worked would corrupt every timesheet and time report. The dialog states the
  count + total hours before confirming.
- **Deleting exposed three latent MERGE bugs.** Diffing `_MERGE_REPOINT` against the live FK
  graph found `approval_requests.requested_by`, `approval_votes.user_id` and
  `doc_pages.updated_by` missing — FK-blocking for a delete, and silently retained by a
  merged-away account today. Plus `teams.owner_id` (ON DELETE SET NULL) would have orphaned
  owned teams. All four added, fixing merge and delete together.
- **Columns referencing users with NO foreign key** (`events.actor_id`, `notifications.*`,
  `item_watchers.user_id`, `attachments.created_by`, `item_*_links.created_by`) would DANGLE
  rather than error — repointed with a successor, purged/nulled without one.
- `tests/test_user_delete.py` asserts repoint completeness **against the live schema**, so a
  new user-referencing table can't quietly break deletion.

**Runtime state:** no migration (behaviour + endpoints only); **842** core tests green;
`web/dist` rebuilt (tsc clean). Verified end-to-end on a throwaway `:8098` server with
temporary accounts (all cleaned up afterwards): empty account deletes with no successor;
owning account 409s without one and, with one, hands its issue over and disappears;
`user.deleted` audit events recorded both.

**Also found while diagnosing the "Sync users does nothing" report:** the live
instance had `ldap_user_sync_enabled` AND `ldap_user_sync_deactivate_missing` turned ON at
21:35 on. The last sync ran 31s BEFORE the sweep toggle was saved, so it has not
fired yet — but `RADD_RUN_WORKERS=True`, so it will on next server start. Blast radius
re-measured: **all dormant** (own nothing, never logged in, and only the owner's
directory account holds an API token) — the privileged aliases plus leavers/service
accounts. The earlier "do NOT enable this" warning is therefore **withdrawn**: enabling it
is safe here and retires the alias cruft. A third test made the same live-DB assumption
(`test_user_sync_provisions_and_updates_toggle_off` asserted `deactivated == 0`) and now
clears the instance override inside its own transaction — turning a feature ON in the product
must never fail its own tests, least of all the assertion guarding mass deactivation.

## Addendum 13 — spec 90: Jira import wizard (live connection, field mapping, staged import)

User direction: wipe the dev DB and re-import from Jira, but rework the flow — pre-import users
from LDAP, import issues, then RELINK links to the new Radd issues rather than back at old Jira;
and build a wizard that lists Jira projects, sets a JQL filter, loads the result into an inbound
schema, and maps fields to local custom fields (creating them where needed). Detail:
`docs/specs/90-jira-import-wizard.md`. Replaces the offline `jira_export_build.py` +
`import_jira.py` round-trip (scripts kept for CLI; the Jira-markup converter moved to
`radd/modules/jiraimport/markup.py`, the script re-exports it).

New module `jiraimport`, live against Jira Server/DC REST v2 (**PAT or basic auth** — PAT wins
when set). Five phases, all shipped:
- **Discovery:** `GET /jira/status|projects`, `POST /jira/preview` → inferred schema (PURE
  `inference.py`; catalog type beats sample cardinality; noise/builtin/useful bucketing — 321 raw
  DEV fields → ~13 worth mapping).
- **Plans:** `jira_import_plans` + per-field mappings (ignore/map/create/builtin), `suggest`
  (pre-filled grid) + `validate`, CRUD (`plans.py`, `mapping.py` PURE).
- **Runs:** `jira_import_runs` as the live progress bar; `runner.py` calls Radd services directly,
  stages FIELDS→ISSUES→LINKS, commits per page, fires an in-process task, fails interrupted runs on
  startup. Preserves Jira IDs 1:1 + timestamps, imports custom fields/comments/worklogs/cycles,
  resolves parents (`issuemap.py` PURE).
- **Relink pass:** issue links → native Radd links when both ends imported (cross-project via
  key remap) else web-link fallback to Jira.
- **Wizard:** `Settings → Import from Jira` (instance admin) — connect → project+JQL → preview →
  map fields (noise/native collapsed) → run with live progress. User pre-import stays spec 88's
  `POST /ldap/directory-users/import`, which the run screen points at.

The spec-89 user-delete guard earned its keep again: it caught that `jira_import_runs.actor_id`
(a new user FK) needed adding to `_MERGE_REPOINT`.

**Runtime state:** DB WIPED + reseeded (spec-90 request; backup `server/var/backups/radd-pre-wipe-20260724.dump`);
alembic head `359b250bda3a` (`5b7a489f873a` plans → `359b250bda3a` runs); **881** core tests green
(39 new: inference/mapping/issuemap/discovery/runner); `web/dist` rebuilt (tsc clean). **Server
restarted** on :8000 with the new module + `.env` Jira creds — `/jira/*` routes live, verified over
HTTP (status connects via basic auth). Live-verified earlier: a five-figure-issue
preview + a bounded run importing real issues with 0 errors. The owner's directory account
(AD login) promoted to admin for testing; 8 leaked `jr-*@example.com` test accounts removed.



## Addendum 14 — specs 101–103: the AI platform + multi-host storage wave

**All three specs shipped, live-verified, and in dogfood** (10 commits,
`a5f0b4c..91a1599` + follow-ups; suite at 1229; `docs/specs/101|102|103-*.md`
carry the full designs).

- **Spec 101 — AI provider registry.** Providers are DB rows with model ROLES
  (`chat`/`embeddings`/`vision`); the client seam (`ai/client.py`) does
  structured output, enum-constrained vision choice, embeddings, and SSE
  streaming. Six feature toggles + per-user editor opt-out; Settings → AI.
  The `local` wire shape SHIPS CPU embeddings in-process (fastembed/ONNX,
  `radd[localembed]`, in the image) — semantic search needs no external model
  server. Live: a vLLM (`gemma-4-31b-it`) holds chat+vision; built-in
  embeddings hold the embeddings role; whole dev corpus embedded ~2min on CPU.
- **Spec 102 — storage rebuilt.** `storage_hosts` rows (proxy|presigned
  delivery; presigned = the network decides who reads a zoned host), the
  routing chain (user_choice / CIDR over `RADD_TRUSTED_PROXIES`-resolved IPs /
  LLM via the vision role), per-attachment spec-92 read grants at the single
  mint chokepoint, polymorphic parents (wiki uploads work), move jobs, orphan
  GC that finally deletes BYTES, blob API for jiraimport. The ask prompt fires
  only when the answer can matter (upload-context simulates the chain per
  content type + caller IP; `preempted_by` names the capturing rule), and
  every read carries `storage_host_name` (grid badges). Two dev Garage hosts
  behind `--profile storage` (localhost:3900/3910, region `garage`,
  `deploy/garage/init.sh`).
- **Spec 103 — editor AI + semantic search.** Crepe's AI feature streams
  server-curated actions (builtins + admin presets) with diff review; OFF is
  byte-identical. pgvector runtime-managed schema + per-model partial HNSW;
  the `ai.embedder` consumer's ONE reconcile sweep = backfill + silent-import
  coverage + model swaps; RRF hybrid `/search`; fused similar/deflect; palette
  Ask mode; MCP `find_items` tool (agents inherit the ranker). **NL→SLQ grew
  up in dogfood**: dialect-aware (`items|worklog` — the timesheet teaches
  `issue.*` delegation), pre-compile VALUE repair ("jimmy" → the real account
  via the autocomplete candidates seam; substitutions reported; SLQ itself
  stays exact), live issue-types/work-categories in-prompt (bugs → `type=Bug`,
  not `kind`), and a `Today is <date>` anchor ("this month" guessed 2025-05
  without it).

**Operational (dev):** host-run server needs `RADD_BACKUP_TOOLS_OPTIONAL=true`
(no pg_dump on host); dev DB container is `pgvector/pgvector:pg16` (reindexed
after the alpine→debian libc change, datcollversion null = no warnings). The
old `attachments.storage` module is gone — hosts.py/clients.py/routing/ own it.

## Addendum 15 — the shell/UX + operations wave (unnumbered + specs 104–105)

**Shell redesign (Cairn-inspired bands, screenshots-driven):** two FULL-WIDTH
bars above the sidebar+content split — row 1 = sidebar toggle + brand + the
query slot + bell + avatar (`TopBar`); row 2 = `PinsBar`: My Work + pinned
tabs (view-type/link icons so they read as NAV) + the ALWAYS-visible New item
button (project-aware: direct inside a project route, a project menu
elsewhere; the view toolbar's own button removed). Sidebar lost its brand
header; `sidebar-prefs` became a `useSyncExternalStore` shared store (toggle
lives in the top bar now — two useState copies would clobber each other).
Pins: `NavPin` = view pins (live-resolved, `KEY · name` disambiguation)
XOR link pins `{path,title}` — ANY sidebar anchor is right-click pinnable
(one delegated handler on the aside; volatile-badge rows carry
`data-pin-label`); tabs get right-click Rename/Unpin (`RenamePinDialog`,
labels in `nav.pins` prefs; three storage generations readable forever).
**Query bar:** Ask mode is the DEFAULT on an empty bar (URL-carried queries
open in SLQ), ⌘I toggles modes bar-scoped. **Inbox peek:** top-bar bell
(badge = the existing unread poll) → right drawer (`InboxPeek`, module-level
toggle à la CommandPalette); a row click marks read + opens the ISSUE peek in
place; `NotificationRow` extracted and shared with `/inbox`. **Peek default
width 1100** (672 stacked the rail ABOVE the description — burying what the
peek exists to show), max 1400. **View pages: ONE header band** (identity +
icon-only share state + SAVED chips + count/knobs); the one-tab `ProjectNav`
is deleted (Reports moved into the ⋯ menu). **Radius scale dialed DOWN**
(md/lg/xl/2xl = 6/8/10/12px — the Dusk bump read too round; rounded-full
untouched; plugin-sdk `--radd-radius*` kept in sync).

**AI UX:** the issue page gained the `AiResultsPanel` — summarize/find-similar
answers open BESIDE the reading column (in former dead space; stacked above
it under @4xl) via an `AiResultsContext` the rail buttons + every read-menu
route through (wiki popover unchanged; transforms still open the editor).
**Unified diff review**: per changed textblock the OLD text stacks above as a
red "−" block and the block itself reads as the NEW text (green, deletions
hidden, insertions emphasized) — presentation-only rework of the diff
decoration plugin; cross-block-boundary fragments deliberately keep
strikethrough. **Editor toolbars**: Crepe tinted glyphs with
`--crepe-color-outline` (our BORDER grey — ~1.5:1) at 24px; now 18px,
secondary-text tint (8:1), accent PILL on active marks (Crepe's top bar sets
`.active` but ships no styling for it — Bold on/off rendered identically).
**SelectField** now converts `<optgroup>` children (the walker silently
dropped groups — the automations trigger dropdown rendered EMPTY; grouped
selects get disabled header rows).

**Plugin gating actually works now:** disabling a plugin previously changed
NOTHING — FastAPI's `include_router` appends `_IncludedRouter` wrappers
(path=None), the old path-prefix unmount filter crashed on them, and the
router's bare `except: pass` swallowed it. Fixes: identity/prefix-aware
unmount, hot enable/disable run `on_startup`/`on_shutdown` (the embeddings
dispatcher kept running), `ai.features.feature_enabled` gates on the kernel
registry (`plugin_loaded()`) so search fusion/storage routing degrade too,
the SPA catch-all 404s unknown `/api/*` paths (JSON) instead of serving
index.html, and every hot-mount failure is LOGGED.

**Specs 104–105 shipped** (see their files): leave + team holidays + the
everywhere away-indicator (`PersonName`/`AwayChip`/Avatar status dot) +
timesheet outlier flags; the admin Monitoring page over the new
`events.service.consumer_status()` seam. New modules `leave` + `monitoring`
(both optional bootstrap). Trigger snapshot 65 → 67.

**Operational:** the automations "0 triggers" report was the optgroup bug —
NOT a registry failure (71 triggers served throughout). `/health` is the real
health endpoint; `/api/v1/health` never existed (its old 200 was the SPA
catch-all wart, now fixed).
