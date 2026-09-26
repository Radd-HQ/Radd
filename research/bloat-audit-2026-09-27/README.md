# Bloat audit — 2026-09-27 (epic RADD-1402)

A read-only audit of the whole repository for dead code, redundant code and over-long comments and docs, split into 15 areas, followed by one fix commit per area. This record keeps what the audit measured and, verbatim, every FLAG it raised: the improvements the epic deliberately did not make because they are beyond a safe mechanical cleanup. The area reports themselves stayed in the session's scratchpad. Machine-absolute paths inside the copied sections are made repo-relative, and names on the owner's publish denylist are replaced with a generic description.

## Line deltas per commit

| Key | Commit | Lines added | Lines removed |
|---|---|---:|---:|
| RADD-1412 | Generated, machine-local and session-only files are ignored, and a local image build no longer copies server/.env | 52 | 18 |
| RADD-1403 | The kernel, spine and infra modules shed dead code, duplicated helpers and history-heavy comments | 1,022 | 2,863 |
| RADD-1411 | Docs and research say what the tree does now; run evidence, per-issue notes and dated reviews leave docs/ | 2,021 | 18,530 |
| RADD-1420 | A pinned wiki page takes the wiki icon: the pins bar keys on the pages plugin's own route | 33 | 2 |
| RADD-1408 | The host SPA sheds its dead code, duplicate helpers and narrated comments | 1,662 | 4,126 |
| RADD-1421 | Print with subpages lists pages in the tree's order, through the one tree-walk helper | 192 | 163 |
| RADD-1422 | Plugin admin pages ask the SDK's useIsInstanceAdmin, which reads the credential-aware role | 41 | 23 |
| RADD-1409 | The SDK, the plugin UIs and their packaging lose their dead code, copies and narration | 1,955 | 5,369 |
| RADD-1413 | Item links and stars go through the row gate every other item write uses | 42 | 11 |
| RADD-1414 | A webhook payload withholds email_signature when the description is read-restricted | 32 | 37 |
| RADD-1404 | The work modules drop dead helpers, duplicated preambles and narrated docstrings without changing behaviour | 2,356 | 5,602 |
| RADD-1415 | The label index keys its readability filter on the page id its rows carry | 45 | 2 |
| RADD-1405 | Service-desk, mail, pages and notify backends shed dead code, duplicate helpers and history narration | 2,767 | 7,977 |
| RADD-1416 | A directory sign-in leaves the instance role alone when no admin groups are configured | 49 | 5 |
| RADD-1417 | A Confluence rollback removes the restriction grants its import wrote | 41 | 11 |
| RADD-1418 | The AI nodes' "Logged time" section carries the item's logged time | 57 | 14 |
| RADD-1419 | The provider Test button sends the row's reasoning preference and extra parameters | 50 | 15 |
| RADD-1406 | Importers, directory, AI and connectors lose their dead code, duplicate helpers and history narration | 1,603 | 4,204 |
| RADD-1423 | perfseed runs on a head database again | 23 | 23 |
| RADD-1407 | Backend tests share one db fixture and user/project factories, and lose dead helpers and narrated docstrings | 1,795 | 6,690 |
| RADD-1410 | Proof scripts share one harness in lib/ and lose their dead, vacuous and drifted checks | 2,645 | 5,992 |
| **Total** | 21 commits (the 10 area cleanups plus 11 bug fixes) | **18,483** | **61,677** |

Net: 43,194 lines fewer across 21 commits, measured with `git show --shortstat` after the cross-area fixups were folded in. Tracked text in the tree (Python, TypeScript, Markdown, scripts) went from 400,361 to about 374,000 lines.

## What was audited

Estimates are each report's own measured totals (lines unless stated), before the fix pass; a fix commit may land less where an item proved wrong or was left for the owner.

| Area | Scope | Files | Lines in scope | Dead | Redundant | Trim |
|---|---|---|---|---|---|---|
| A — kernel + spine (backend) | `server/src/radd/kernel`, `config.py`, app-level modules and the spine utilities | 145 .py | 18,072 | ~105 | ~390 | ~1,460 |
| B1 — items, views, workflow, fields, comments, participants, weblinks, linktypes, labels (backend) | those modules' non-`ui/` Python | 130 .py | 20,621 | ~55 | ~685 | ~650 |
| B2 — auth, projects, teams, groups, cycles, releases, milestones, itemtypes, timelogging, leave, reporting, dashboards (backend) | those modules' non-`ui/` Python | 139 .py | 21,916 | ~200 | ~480 (+~250 if dashboards/views sharing is unified) | ~1,640 |
| C1 — automations, scripts, approvals, slas, forms, csat (backend) | those modules' non-`ui/` Python | 88 .py | 17,182 | ~210 | ~480 | ~1,415 |
| C2 — notify, mailintake, pages, collab, attachments (backend) | those modules' non-`ui/` Python | 123 .py | 21,082 | ~104 | ~365 | ~2,880 |
| D1 — jiraimport, confluenceimport, ldap, sso (backend) | those modules' non-`ui/` Python | 91 .py | 18,439 | ~470 | ~800 | ~600 |
| D2 — ai, vcs, gitlab, github, forgejo, alertmanager (backend) | those modules' non-`ui/` Python | 84 .py | 14,667 | ~65 | ~1,350 net | ~560 |
| E1 — host components (incl. the roadmap part) | `web/src/components/` minus `settings/`, `shell/` | 192 TS/TSX + 2 CSS | 30,604 | ~80 | ~470 | ~800 |
| E2 — host lib, routes, settings, shell, root | `web/src/lib`, `routes`, `components/settings`, `components/shell`, `plugins`, root files | 245 TS/TSX + CSS | 36,738 TS + 573 CSS | ~225 | ~115 | ~690 |
| F — plugin SDK + the six largest plugin UIs | `web/packages/plugin-sdk`, `automations/ui`, `pages/ui`, the importer UIs, `ai/ui`, `dashboards/ui` | 255 | 29,517 | ~103 | ~807 | ~1,411 |
| G — small plugin UIs + packaging | 34 plugin UI packages, build tooling, `web/public/shared`, `examples/acme-notes` | 305 | 15,243 | ~65 | ~790 | ~500 |
| H — proof scripts | `web/scripts` (proofs, unit tests, `lib/`, suite runners) | 193 .mjs | 30,974 | ~490 | ~1,670 | ~220 |
| I — prose: docs, specs, PLAN/BUILD-LOG/CLAUDE.md, research | `docs/` (30 docs + 131 specs), the four root narratives, tracked `research/`, 3 package READMEs | ≈251 (30 docs, 131 specs, 4 root, 83 research, 3 READMEs) | ≈46,500 (3.85 MB) | ≈17,490 (+1,359 moved) | ≈1,750 | ≈520 lines / ≈465 KB |
| T — server tests, scripts, migrations | `server/tests`, `server/scripts`, `server/migrations` (history, left alone) | 319 tests + 10 scripts (+216 migrations) | 75,391 (+13,126 migrations) | ~130 | ~4,090 | ~1,780 |
| J — repo hygiene | every tracked file, ignore rules, secrets, the publish gate | 2,915 tracked | 22.9 MB | 10 files / 430 KB clear-cut (+17 JSON / 914 KB by policy) | — | — |

## FLAG items, by area

Each area below is copied verbatim from each report's FLAG section (area J has none; its "Decisions for the owner" is copied instead). E1's FLAG already contains its roadmap part in full. F's four part reports carry FLAG sections of their own, copied after F's.

## FLAG — A — kernel + spine (backend)

- **Bug — `events/service.py:170` reads `settings.debug`, but `config.Settings` has no `debug` field.**
  - Evidence: `grep -n debug server/src/radd/config.py` returns nothing. Pydantic raises AttributeError on an unknown attribute.
  - Effect: an undeclared subject passed at a call site raises AttributeError from inside `emit`. The documented "degrade to `{id}` in production" never happens, so the branch at 175-176 is dead.
  - Direction: pick one behaviour. Either always raise with the clear RuntimeError message, or add a real `debug` setting.
  - Size: ~6 lines.
- **Bug risk — `backup/service.py:209,284,362` use `asyncio.create_task(...)` fire-and-forget without keeping a reference.**
  - asyncio keeps only weak references to tasks, so a running backup or restore task can be garbage-collected. These tasks also bypass `kernel.admission.spawn`, which exists to adopt request-spawned jobs.
  - Direction: `spawn(...)`, or keep a module-level task set.
  - Size: ~3 lines.
- **Wire inconsistency — `backup/schemas.py` uses plain `datetime` for `next_run_at`, `last_run_at`, `created_at`, `started_at` and `finished_at` instead of `radd.apitypes.UtcDatetime`.**
  - These naive-UTC values leave without `Z`, which is exactly the "4 hours ago" bug `apitypes.py` was written for.
  - Size: ~7 fields.
- **Abstraction with one user — the `TaskSpec` / `Socket.TASK_BACKEND` / `settings.task_backend` / `LocalLoopBackend`.**
  - There is one provider (`localloop`) and one production `TaskSpec` (`access.expiry-sweep`). Meanwhile 16 modules still hand-roll `PeriodicLoop`, including `events/cascade.py`, `search/dispatcher.py`, `webhooks/dispatcher.py` and `backup/scheduler.py`, although `TaskSpec`'s docstring says consumers register these "instead of hand-rolling PeriodicLoops".
  - The "celery" provider in comments (`capabilities/__init__.py:20`, `sockets.py:27`, `config.py:73-75`, `worker.py:19`) never existed.
  - Direction: either migrate the periodic loops onto `TaskSpec` (and delete `on_startup`/`on_shutdown` loop wiring in ~16 plugins), or drop the socket and backend indirection and keep `PeriodicLoop`. Do not keep both.
  - Size: ~40 lines either way.
- **A consumer that names plugins — `mcp/types.py:53-90` (`McpTool`, 31 names) and `mcp/catalog.py:32-69` (`CATALOG_ORDER`).**
  - The mcp plugin hardcodes the tool names of items, timelogging, releases, pages, projects, auth and search, only to order the catalog and split builtin from plugin tools. The owner modules declare the same names as strings, so there are two copies of every name, and a rename silently drops the tool from the ordered section.
  - Direction: an `order: int` on `McpToolSpec`, then sort the registry. This deletes `McpTool`, `CATALOG_ORDER`, `_BUILTIN_NAMES`, `PAGE_TOOLS` and the `registry_catalog` split.
  - Size: ~80 lines.
- **Two off-switches for MCP — `mcp/router.py:128,204` gate on `settings.mcp_enabled` (`RADD_MCP_ENABLED`) while `mcp` is `core=False` and disableable in the plugin manager.**
  - Direction: drop the env flag, or document why both exist.
  - Size: ~8 lines plus the config field.
- **Core naming an optional plugin and a hardcoded prefix — `collection_compression.py:16-18`.**
  - It hardcodes `/api/v1/...` (instead of `settings.api_prefix`) and the slas plugin's `/sla-queue-items` path (`slas/types.py:33`). That is a core file reaching an optional plugin by string (development rule 1).
  - Direction: build the set from `settings.api_prefix` plus the registered `ViewListSpec.rows_path`s.
  - Size: ~5 lines.
- **Forbidden guard pattern — `realtime/hub.py:137-141` uses `settings.modules` as a feature guard, which CLAUDE.md forbids.** `items` is core (never disableable) and `realtime` already `weak_depends` on it.
  - Direction: import it directly.
  - Size: ~5 lines.
- **`radd/smtp.py` belongs in mailintake.** Its only caller is mailintake, which is an optional plugin (`senders/smtp_sender.py`).
  - Direction: move it to `mailintake/senders/`.
  - Size: file move.
- **Generic hooks with 0 or 1 users (flag only; they are SDK-visible):**
  - `NavItemSpec.capability`: no plugin sets it, although the SPA filters on it in 3 places.
  - `ViewListSpec` (slas only).
  - `CascadeSpec.after_commit` (attachments only).
  - `ResourceSpec.roles_for` (attachments only).
  - `RaddPlugin.openapi_augmentors` (fields only).
  - `SettingSpec.multiline` (mailintake only).
  - `SettingSpec.config_attr`: ldap only. It exists so that `ldap_user_sync_base` defaults from `ldap_user_search_base`; renaming either one deletes the field and the indirection.
- **Oversized files (with seams):**
  - `kernel/specs.py` (1,091 lines; ~775 after TRIM): split the automation specs (lines 411-757) into `specs_automation.py`, and the access/relation specs (238-362, 867-918) into `specs_access.py`.
  - `search/service.py` (567): the relation/guard compilation (91-251) into `search/scope.py`; the similarity and embedding seams (413-567) into `search/similar.py`.
  - `pluginmgr/service.py` (445): contribution settings (255-320) into `contributions.py`; `sweep_plugin_atoms` (323-404) into `atoms.py`.
  - `access/service.py` (445): the shared-resource SQL seams (96-145) and restriction modes (418-445) into `shared.py` and `restrictions.py`.
  - `kernel/entities.py` (434): `crud_router` (272-416) into `entities_router.py`.
  - `backup/service.py` (405): schedules versus runs.
  - `events/service.py` (391): the read side (`query_events`, `entity_activity`, `consumer_status`) into `reads.py`.
  - `kernel/registry.py` (458): see the table-driven REDUNDANT item.
- **Back-compat ceremony (the "no backcompat until V1" memory):**
  - `webhooks/dispatcher.reencrypt_secrets`, `service.encrypt_plaintext_secrets` and `secretbox.decrypt`'s plaintext passthrough exist only for legacy plaintext rows.
  - `config.smtp_from_address`'s double alias.
  - Direction: drop these once live rows are encrypted.
  - Size: ~25 lines.
- **Doc drift:**
  - `docs/modules.md` settings rows (170, 298) describe `SettingSectionSpec`, `settings_sections` "still unwired" and the `release_*` keys; none of these exist any more.
  - `docs/plugin-platform.md:336-349` lists the Notifier, AttachmentFilter and Connector sockets.
  - `kernel/plugin.py:5` says "All 49 builtin plugins"; there are 58.
  - `kernel/capabilities.py:54` and `capabilities/router.py:47` refer to `/instance/status`, which no longer exists.
  - `webhooks/router.py:26` names the wrong permission.
  - `plugin_cli.py:201` says "A fresh output directory…", but the code does `mkdir(exist_ok=True)`.
  - `runner.py` names `googlechat`.
- **Minor:**
  - `audit/service._projects_by_id` loads every project for each audit page.
  - `access/service._subject_label` has no GROUP branch, so audit rows show a group grant as a bare uuid.
  - `pluginmgr/discovery.all_known()` calls `core_plugins()` twice (directly, and via `installable_plugins`).
  - `kernel.changes.changed_fields` is test-only but public via `radd.sdk.changes`.
  - Lint: B007 at `pluginmgr/boot.py:62` (use `_plugin`), and SIM105 at `realtime/broadcaster.py:46,117` and `kernel/admission.py:193`.

## FLAG — B1 — items, views, workflow, fields, comments, participants, weblinks, linktypes, labels (backend)

Correctness items come first, then file splits, then pattern inconsistencies.

- **`items/service/links.py:186-229`: item links are missing the row gate. This is a correctness issue.**
  - `add_item_link` and `remove_item_link` call `authz.require(ITEM_UPDATE, project=...)` but never `ensure_item_relation`. Every other item write does (`core.py:209,347,444,372`, `convert.py:49`, `merge.py:148-149`).
  - Result: an actor holding only `item.update@own`, or a relation-qualified scoped key, can add or remove links on items that are not theirs. The MCP `link_items`/`unlink_items` tools inherit this ("Enforcement is `add_item_link`'s own", `mcptools.py:153`).
  - Direction: the `require_item_permission` helper in REDUNDANT fixes it by construction. Verify with an `@own` actor first.
  - Size: about 4 lines.
- **`items/service/core.py:410-431`: `star`/`unstar` skip the relation gate. This is minor.**
  - `_require_readable` checks project `item.read` only. `unstar` on a hidden or restricted item answers 204, while a missing item answers 404 and `GET` answers 404. That is an existence oracle (spec 57's rule).
  - `star_item` inserts the row, and then `get_item` 404s; the request rollback discards it.
  - Direction: use `require_readable_item`.
  - Size: about 3 lines.
- **`items/redaction.py:17-32`: webhook redaction misses `email_signature`. This is a correctness issue.**
  - The API read blanks BOTH `description` and `email_signature` when `description` is read-restricted (`visibility.py:277`).
  - The webhook mirror blanks only `description`. `ItemRead.email_signature` is in the payload (`schemas.py:325`), so a webhook receiver still gets the signature text.
  - Consolidating the two maps (REDUNDANT) fixes it.
  - Size: about 1 line.
- **The views can-manage drift. This is a correctness issue.** See REDUNDANT: an owner-less all-projects view is judged by GLOBAL `view.update` in `_can_manage_view` and `_hydrate`, but by `require_anywhere` in `_require_manage`. The UI's `can_manage` and the enforced gate can therefore disagree.
- **`comments/parents.py:56-57` vs `comments/service.py:232-254` and `reading.py:40`: the page-comment manage permission.**
  - `CommentParent.manage_permission` is only read by `resolution.resolve_reach`.
  - Editing someone else's comment (`_require_author_or`) and the see-all audience (`reading.audience`) hardcode `Permission.PROJECT_MANAGE`. On a page (project None, binding `PAGE_MANAGE`) that means GLOBAL `project.manage`.
  - `_require_author_or` also checks `comment.write` with `project=None`, while the page binding writes with `space_id=` scope.
  - Direction: verify with a space-scoped actor, then route through the binding.
- **`fields/openapi.py:13-20`: the process-wide `schema_cache` has two problems.**
  - `service.extend_options` does not refresh it, so new select options are missing from `/openapi.json`.
  - `mcp/catalog.py:157` refreshes it without `restricted_keys`, which strips the `x-restricted` hints.
  - Direction: return the properties instead of mutating a global, or have MCP pass the restricted keys.
  - Size: about 10 lines.
- **`items/mcpschemas.py:22-33` (`_SLQ_DOC`) has drifted from the SLQ catalog.**
  - It lists 23 builtin fields and omits `type`, `points`, `visibility`, `epic`, `epic.*`, `parent.*`, `past_cycle` and `cycle.status` (compare `slq/catalog.py:21-66`). It also omits the relative dates (`today+3d`).
  - Agents read this string.
  - Direction: build the field list from `SlqField` and `BUILTIN_OPS` (filterable ones) so it cannot drift.
  - Size: about 5 lines.
- **`views/service.py` (1,068 lines): split.**
  - `views/access.py`: `VIEW_RESOURCE`, the `_shares_by_view`/`_grant_level`/`_can_manage_view`/`_lock_view`/`_view_labels`/`_VIEW_SPEC` block, `_scope_permissions`, `_sharing_state`, `_require_scope`, `get_view`, `_load_visible`, `visible_view`, `_require_edit` and `_require_manage` (`:62-199,322-329,510-606`, about 245 lines).
  - `views/validation.py`: `_scope_definitions`, `_validate_query`, `_ORDER_BY_RE`, all the `_validate_*` functions, and `_validate_bucket_order` pulled out of `schemas.py:145-149` (`:333-508,612-620`, about 190 lines).
  - `views/hydration.py`: `_hydrate` and `_hydrate_one` (`:201-319`, about 120 lines).
  - `views/presets.py`: the card-layout presets (`:943-1029`, about 90 lines).
  - CRUD, sharing, transfer, members and `_emit` stay (about 400 lines).
  - If the access consolidation lands first, `access.py` shrinks to about 100 lines.
  - Size: no net change; 1 file becomes 5.
- **Views and dashboards duplicate more than the helper set.** `_transfer_ownership` (`views:820-877` vs `dashboards:502-555`), `_update_sharing`, `_require_edit`, `_require_manage`, `_load_visible`, and the share half of `_hydrate` are also parallel. A generic owned-resource module taking the per-module predicate would remove about 100 more lines from each. Size: about 200 lines across both.
- **`workflow/transitions.py` (696 lines): split.**
  - `transitions.py`: CRUD, audit and emit (about 250 lines).
  - `transition_rules.py`: `_validate_rules`, `_validate_field_rule`, `_validate_enum_values`, `_require_iso_date`, `_require_number` and `_validate_on_release` (about 160 lines).
  - `enforcement.py`: `resolve_mode` through `allowed_transitions` (`:386-648`, about 265 lines).
  - The direct importers must follow: `approvals/service.py:37` and `items/mcptools.py:31`.
- **`fields/service.py` (702 lines): split.**
  - `access.py`: lines `33-118` and `448-685` (the ResourceSpecs, `FieldAccessContext`, readable/writable, the builtin denial checks, `build_field_ctx` and `readonly_field_keys`; about 330 lines).
  - `service.py` keeps the definition CRUD, option migration and registry reads (`121-446`; about 330 lines) and re-exports, because there are 30+ `fields.<name>` call sites.
  - `_refresh_cache` and `warm_schema_cache` (`687-698`) move into `openapi.py`, which owns the cache.
- **`comments/service.py` (578 lines): split.**
  - `rows.py`: `_to_read`, `_team_restrictions` and `_set_teams` (`35-121`). These are pulled out of service by deferred imports from `reading.py` and `threads.py`; moving them breaks the service↔reading↔threads cycle.
  - `seams.py`: the cross-module read seams (about 130 lines), re-exported.
  - The write path stays (about 330 lines).
- **`items/mcptools.py` (605 lines): split.** The file holds four things: name resolvers (`55-84`), result shapes (`87-133`), 13 handlers, and 13 specs, four of them with inline schemas.
  - Seam 1: move the inline schemas to `mcpschemas.py` (REDUNDANT).
  - Seam 2: move the four structural tools — move, clone, convert and merge (`441-589`, about 150 lines) — to `mcptools_structure.py`.
  - The name-to-id resolvers (`_state_id`, `_type_id`, `_cycle_id`, and the copies in `forms/service.py:308` and `timelogging/mcptools.py:34`) belong in their owners' services.
  - Size: about 150 lines move, about 25 are saved.
- **`items/service/visibility.py` (547 lines): split.** It holds three concerns.
  - Row access: the relations, the row guard, `relation_read_clause`, `attach_capabilities`, `ensure_item_relation` and `require_key_item_permission` (`24-268,540-547`; about 255 lines).
  - Field access: `_BLANK_BUILTIN`, `_filter_read`, `_builtin_read_denied`, `_BUILTIN_FIELD_MAP`, `_check_builtin_field_rules`, `_field_ctx`, `_internal_visible`, `_BUILTIN_TO_SLQ_FIELDS` and `denied_slq_fields` (`270-493`; about 225 lines).
  - Project visibility (`496-537`).
  - Proposal: `rowaccess.py` and `fieldaccess.py`, with `visibility.py` kept as a re-export. Size: a move.
- **`items/service/core.py` (520 lines): split.** The create/update flow (`56-307`, about 250 lines) vs lifecycle operations: reassign, archive, delete, stars, rank, cycle move and email signature (`310-520`, about 210 lines). Seam: `lifecycle.py`. Size: a move.
- **`items/bulk.py` (439 lines): the id listing is not "bulk".**
  - The id-listing half (`list_item_ids`, `visible_matching_ids` and `count_items`, `374-439`) belongs in `service/scope.py` or `service/listing.py`.
  - `reporting/service.py:23` and `automations/engine.py:51` import `radd.modules.items.bulk` directly, reaching past the service surface (rule 1).
  - Direction: export these through the service barrel.
  - Size: about 65 lines move.
- **`items/grouped.py:20-287`: `grouped_items` is one 267-line function.**
  - Seams: request validation (`21-35`), the query and axis build (`36-94`), the summary aggregate (`95-167`) and the cell-window fetch (`168-287`).
  - It also has four in-function imports with no cycle reason (`:39`, `:82`, `:146`, `:168`) and string literals for categories (`:87`).
  - Size: about 0 lines saved; readability.
- **Other modules import `items/service/visibility.py` internals directly.** There are 11 sites: `ai/similar.py:187`, `approvals/service.py:371,461,567,619`, `pages/links.py:141`, `participants/service.py:20`, `search/deflect.py:96,122`, `timelogging/worklog_router.py:86`, and `weblinks/router.py:29` / `mcptools.py:26`.
  - Two of those names (`ensure_item_relation`, `relation_read_clause`) are exported by the barrel anyway. `require_key_item_permission` is not.
  - Direction: add it to the barrel and import through `items.service` everywhere. The seam is applied inconsistently.
- **`workflow/service.py:223-229`** re-exports functions "because modules talk through public service functions". Yet `items/mcptools.py:31` and `approvals/service.py:37` import `workflow.transitions` directly. Either re-export what they use or drop the rationale.
- **`items/rollup.py:100-114`: an unreachable `except ImportError`.**
  - `try: from radd.modules.timelogging import service … except ImportError: pass`. The package is always importable, and timelogging is core, so the branch cannot run. CLAUDE.md rule 1 says `except ImportError` "is never a guard".
  - Direction: use a plain deferred import. Items already `weak_depends` on timelogging.
  - Size: about 4 lines.
- **`items/slq/suggest_values.py:47-73,159-160`: `_DB_BACKED_FIELDS` is a 19-member set that exists only so tests can call `suggestions_for(None, …)`** ("session is always real in production"). It is a hand-maintained test accommodation in production code; a new DB-backed field must be remembered here (spec 83 says so). Direction: pass a stub session in `tests/test_slq_suggest.py`. Size: about 25 lines.
- **`items/listing.py:4-5` and `compiler.py:139-157`: label resolution.**
  - `listing.py` says expression GIN indexes "come later via the field registry's `indexed` flag". Nothing reads `FieldDefinition.indexed` (the fields fork confirms it is write-only).
  - Label resolution scans all in-use labels per query (see REDUNDANT).
  - Direction: drop the promise, or build the index.
- **`views`: unused endpoints.** `PUT /views/{id}/sharing`, `POST /views/{id}/transfer`, their service wrappers and `GET /views/summary` have no SPA or proof caller. `apiViewSharingPath` and `apiViewTransferPath` are defined in `web/src/lib/constants/api-paths.ts:74,76` and never imported. These are public REST, so removing them is the owner's call. Size: about 60 lines plus tests.
- **`views/service.py:376,387`: `_ORDER_BY_RE` rejects `title ~ "order by"`** as an ORDER BY. `slq.parse(q).order` already knows. This is a behaviour change.
- **`views/models.py:100-101`: `ViewMember.position` is never written or read.** It is a speculative column; dropping it needs a migration.
- **`fields`: write-only flags.**
  - `FieldDefinition.indexed` and `FieldSource`/`source`: nothing reads them, nothing produces `CONNECTOR`, and "read-only in the UI" is not implemented.
  - The scope-ladder rule is implemented three ways with different atom semantics (`router.authz.require`, the exact-atom `in effective_permissions`, and `Policy.holds_base`).
- **`comments`: drift and inconsistencies.**
  - `_COMMENT_PAYLOAD_SCHEMA` (`__init__.py:36-49`) omits `is_thread`, `origin` and `author`.
  - `reading.py` and `threads.py` raise FastAPI `HTTPException` from the service layer.
  - `automation.py:52,57` use literals where constants exist.
  - `gc.py` and `attachments/gc.py` build the same cascades wrapper; that belongs in the kernel.
- **`docs/modules.md:180,189` have drifted.**
  - The linktypes row lists `is_auto_managed` and `resolve_by_name` (DELETE above).
  - The views row mentions `share_count`, `workspace_access`, the legacy `shared:true` alias and `ViewType.QUEUE`.

---

## FLAG — B2 — auth, projects, teams, groups, cycles, releases, milestones, itemtypes, timelogging, leave, reporting, dashboards (backend)

- **F1** `server/src/radd/modules/dashboards/service.py` (607 lines) vs `views/service.py` (1,070) — dashboards re-implements views' owned-and-shared resource layer function-for-function (`_shares_by_*`, `_grant_level`, `_can_manage_*`, `_lock_*`, `_*_labels`, `_hydrate` share-ref block, `_sharing_state`, `_load_visible`, `_require_edit`, `_require_manage`, `_validate_global_access`, `_add_share`, `update_sharing`/`_update_sharing`, `transfer_ownership`/`_transfer_ownership`, `_delete_user_*`, `save_*`); the module docstring even says "the spec-57 view idiom VERBATIM". Two computations of the actor's level also coexist inside dashboards (`_grant_level` in Python over loaded shares vs `_sharing_state` in SQL). Direction: one parameterized helper in `access` (model, resource_type, owner/global columns) used by both. **~250 lines.**
- **F2** `server/src/radd/modules/dashboards/types.py:18-20`, `schemas.py:22-24,62-66,148-150`, `widgets.py:85` — core dashboards still owns the SLA widget of the *optional* `slas` plugin (`WidgetType.REPORT_SLA`, `ReportSlaConfig`, a mirrored `SLA_MAX_WEEKS`, a `_check_references` branch). Since RADD-1386/1393 the right shape is a `WidgetTypeSpec` contributed by slas (as approvals does for My Work). ~20 lines out of core.
- **F3** `server/src/radd/modules/dashboards/activity.py:53`, `personal.py:130` + `__init__.py:46` (`weak_depends=("comments","forms")`) — `"comments"/"forms" in registries.plugins` guards on two CORE modules (neither is `core=False`, both are in the default `RADD_MODULES`). They buy something only if an operator trims core modules from `RADD_MODULES`; if that is unsupported, make them plain imports. Also `activity.py:11-21,44,49,52,58,68` hardcode event-type and entity strings (`"item.created"`, `"comment."`, `"item"`) — dev rule 2 says enum members (`ItemEvent`, `CommentEvent`, `WorklogEvent`); `personal.py`/`router.py` raise `ConflictError("dashboard", …)` with a literal instead of `DashboardEntity.DASHBOARD`, and `personal.save` imports the private `router._parse_widget_body` (service → router dependency).
- **F4** Files over ~300 lines with a clear seam: `auth/types.py` 895 (BUILTIN_ROLES seed data :614-841 → `roles_seed.py`; relations algebra :447-518 → `relations.py`); `auth/router.py` 867 (service accounts :767-867 → `service_account_router.py`; inspector routes :296-481 → `inspector_router.py`); `auth/schemas.py` 690 (roles/grants :458-690 → `roles_schemas.py`); `auth/lifecycle.py` 652 (the repoint tables :31-191 → `lifecycle_tables.py`); `auth/grants.py` 624 (resolution :29-193 vs CRUD :277-576); `auth/service.py` 571 (TOTP :350-480 → `totp_service.py`); `auth/roles_router.py` 565 (role_grant_router :302-565); `cycles/service.py` 663 (series :414-586 → `series.py`); `timelogging/service.py` 568 (authorization :339-402 + estimate :462-537); `teams/service.py` 567 (stewardship :312-466); `groups/service.py` 417 (sync writes :296-417 → `sync.py`); `teams/router.py` 388.
- **F5** `kernel_enforced=False` MCP tools that re-do the kernel's job: `releases/mcptools.py` (all six), `auth/mcptools.py` (three), `timelogging/mcptools.py:log_work` each call `authz.require` in the handler for the same atom the spec declares, often with `project_param` set — the pattern `projects/mcptools.update_project` and `milestones/mcptool` show (kernel-enforced, no handler check) would delete the handler checks and `_project_for` helper. Needs per-tool confirmation that the kernel resolves the project the same way.
- **F6** Magic strings where rule 2 wants enums: `projects/directory.py:54,67` compare `row.via.value == "related"` (use `ProjectVia.RELATED`); `releases/models.py:21` `default="planned"`; `roles_router.py:553` `NotFoundError("role grant", …)`; `service_accounts.py:164` `NotFoundError("api_token", …)` (both have `AuthEntity` members); `milestones/mcptool.py:30` `NotFoundError("project", …)`.
- **F7** (bug risk found on the way) `auth/grants.py:141-172` `attributed_rows_for_user` builds its own subject condition WITHOUT `_live()` and WITHOUT the principal rows (`subject_user_ids`), unlike `_subject_condition`. The permission inspector therefore lists EXPIRED grants as sources and omits grants held via Anyone/Signed-in users — describing rules enforcement does not follow. `models.py:244-246`'s claim that "every GlobalRoleGrant query carries the liveness clause" is false (also `grants_for_subject`, `grants_for_project/space`, `role_referenced` — some deliberately).
- **F8** (bug risk) `timelogging/slq/suggest.py:146-155` — author value suggestions select every active `User` with no `NON_PERSON_SOURCES` filter, so `anyone@principals.invalid` / `signed-in@principals.invalid` and mail-provisioned requesters are offered; it also re-implements the item dialect's ranking/quoting/operator list (`_rank`, `_quote`, :74-81) that `items/slq/suggest.py` keeps private. ~40 lines if items exported them.
- **F9** Per-row queries: `auth/entityhost.py:114-116` (`get_project` + `effective_permissions` per row; `permissions_for_projects` exists), `auth/role_options.py:43-48` (`ensure_delegated_role_coverage` → `effective_permissions` per role), `leave/router.py:21-35` (`get_team` per leave row), `leave/service.py:37-39` (`is_team_steward` per team), `timelogging/service.py:208-213` (`get_project` per distinct project), `auth/mcptools.py:25-29` (loads every user, then slices to `limit`).
- **F10** `auth/role_options.py:37` and `projects/router.py:124` import `ensure_delegated_role_coverage` from `auth/roles_router.py` — a policy helper living in a router, imported by a service module and by another module's router. It belongs in `roles.py` (or `grants.py`).
- **F11** Two listings of one resource: `GET /service-accounts/{id}/keys` (full `TokenRead` incl. scopes) and `GET /service-accounts/{id}/keys/directory` (paged summary). The SPA uses only `/directory`; `web/src/lib/queries/integrations.ts` still defines the unused `serviceAccountKeysQuery` and `serviceAccountsQuery` (web area). The full list is public API and tested (`test_service_account_directory.py:148-149`), so decide deliberately.
- **F12** Doc drift for this area in `docs/modules.md` (another area's file, but it describes these modules): the auth row still says "builtin admin/member/viewer", "`baseline` … seeded `item.read` + `page.read`", "`authz.is_admin` is the one admin predicate", "`service_account.create/update/delete`"; the cycles row lists `active_cycles` as a helper others import and "`Permission.CYCLE_MANAGE`"; reporting mentions `item_state_timeline`.
- **F13** Cross-area notes for other auditors: `web/src/components/settings/AccessInspector.tsx:186-190` renders `via === "membership"` (no longer produced) and calls `via === "team"` a "project attachment"; `server/src/radd/modules/ai/nlslq.py:73-76` guards the CORE timelogging module with `except ImportError` and compiles worklog SLQ without `hours_per_day`/`denied_item_fields` (see the worklog-SLQ compile entry under REDUNDANT); `server/src/radd/modules/settings/types.py:171,193` cite `_DescriptionCatalog` as a precedent.

---

## FLAG — C1 — automations, scripts, approvals, slas, forms, csat (backend)

- **`forms/staging.py:121-147` — `sweep_abandoned` is dead, and the feature it claims never runs.**
  - The docstring (`:124-125`) and the `ParentBinding` comment (`:87-89`) say it "emits `form.staging.deleted` for each" area so the spec-102 cascade reclaims rows and bytes. It never emits anything: it returns ids, and nothing in `server/src` calls it.
  - Evidence:
    - `git grep -n sweep_abandoned` shows only `tests/test_submission_attachments.py:170`, `:184`.
    - `git grep -n STAGING_DELETED` shows only its registration and the binding.
    - It has been this way since RADD-800 (`git show 849caac3:…/staging.py`).
  - Result: `form.staging.deleted` never fires, and abandoned submission attachments and their bytes live forever.
  - Direction: wire it into a `PeriodicLoop` that emits the event per area. Otherwise delete `sweep_abandoned`, the `STAGING_DELETED` event type, the `deleted_event` binding and `attachments.service.newest_per_parent` (~45 lines).
- **`automations/service.py` (1,024 lines) — split.** Lines 56-600 are write-time graph validation: `_validate_graph`, the `_check_*` functions, `_tokens_in` and `_require_node_permission`. Move them to `writecheck.py`. CRUD and the binding syncs stay in `service.py`. Est. ~545 lines move.
- **`automations/executor.py` (1,064 lines) — split.** `_NodeContext` plus `_context` (`:629-858`, ~230 lines) is the contributed-node API; move it to `context.py`. The walk, the runners and the budget stay.
- **`automations/schemas.py` (988 lines) — split after the `ACTION_PARAMS` consolidation.** The catalog, preview and run read models (`:567-988`) go to `read_schemas.py`; the action params stay.
- **`automations/planning.py` (924 lines) — split.** `_plan_action`'s 26-arm `match` (`:611-924`) goes to `builtin_planners.py`. `load_item_facts`, `_item_ctx` and `items_ctx` (`:398-506`) go to `itemfacts.py`.
- **`automations/engine.py` (808 lines) — split.** `preview`, `_result_of`, `_keys_for`, `_produced` and `_node_results` (`:605-808`) go to `report.py`.
- **`approvals/service.py` (662 lines) — split.** The read hydration (`_reads`, `pending_for_user`, `item_approvals`: ~250 lines) goes to `reads.py`.
- **`forms/service.py` (561 lines) — split.** The submit path (`:287-521`) goes to `submit.py`.
- **`ActionPreview.params` is unrendered and heavy.** `executor.py:911`, `:954`, `:983` and `:1022` copy `dict(node.params)` into every `PlannedAction`; `engine._result_of` then stores it in every `automation_runs.report` row. For `script.run` that includes the whole `body` (`maxLength` 200,000), once per item at item arity. No UI reads it; the node's params are already in the graph under `node_id`. Direction: drop the field (one test, `test_second_review_interactions.py:686`), or keep only the rendered `resolved` map.
- **The item key spelling (`f"{project.key}-{item.number}"`) is rebuilt in five places in scope:**
  - `engine._keys_for` (`:741-748`, with its own join);
  - `planning._item_ctx` (`:472`);
  - `approvals/service.py:650`;
  - `csat/service.py:75`;
  - `forms/requests.py:179`, which also fetches `project_keys` although `project.key` is already in hand.

  `items.service.refs.ref_from` owns the spelling. `engine._notification_item_ref`'s own docstring says "the key's spelling is items' to own", and `_keys_for` below it breaks that rule. Direction: add an `items.item_keys(session, ids)` seam.
- **Descriptions that no longer match the code:**
  - `automations/__init__.py:108`: the `automation.manage` permission description says rules change issues "through the system actor", but they run as the author since spec 116. Same for the `router.py:58-59` comment.
  - `service._check_validate_trigger` (`:430`) cites "the send_email role check", which moved to mailintake.
  - `test_automations.py:1-8` still points at the deleted `scripts/demo_automations.sh`.
- **Bare wire literals, against CLAUDE.md rule 2:**
  - `"trigger.event"` in `builtin_routers.py:245`, `templates.py:45-46` and `mailintake/automation_email.py:246`;
  - `"gate.entered_state_category"` in `builtin_routers.py:99`;
  - `executor.add_finding` writing `"required"`/`"advisory"` rather than `ValidationMode` values (`:821`);
  - the gates `MODE_*` plain strings.
- **`planning._Plan.http` (`planning.py:199`)** is annotated `tuple[str, dict, dict[str, str]]`, but the third element is the signing secret, a `str` (`:653`, `engine.py:159-163`).
- **`forms/schemas.py:330-332` and `:341-349`:** `email_signature: str | None = None` sits ABOVE the docstring in `PortalRequestComment` and `PortalRequestDetail`. The "docstring" is therefore a dead string expression, and neither class has a `__doc__`. Move the field below the docstring.
- **Misleading forms class names.** `PublicFormField`, `PublicFormRead` and `PublicSubmitResult` are misnomers since RADD-828 removed the anonymous path. They are the portal's trimmed shapes now, and the TS mirrors (`web/src/lib/types/forms.ts`) carry the same names. A rename is cross-cutting.
- **Full lists computed for a yes/no answer:** `approvals.has_pending` (`service.py:590-593`) and `forms.portal.nav_portal_visible` (`portal.py:133-138`) build the whole list, with per-project lookups, to answer a bool on every My Work or nav render. This is not bloat but a cost: an `EXISTS` query would do.
- **`{{token}}` grammar copies outside this area:** `canned/render.py:11` and `mailintake/service.py:190` re-declare the regex that `automations.templating.TOKEN_RE` exports "so a second regex cannot admit something this one does not".
- **The `"cf."` prefix is defined in three places:** `automations/service.py:50` (`CUSTOM_FIELD_PREFIX`, unused in `service.py`; only `verdicts.py:67` imports it), a copy at `ai/automation_node_validate.py:304` and `views/types.py:42` (`CF_AXIS_PREFIX`). Direction: one constant in `fields.types`.
- **`scripts/runner.py:85` — `RADD_URL` is placed in the child's environment**, but the harness reads the URL from stdin (`harness.py:37`), STARTER_SCRIPT does not document it, and the token is never in the environment, so a script cannot build a client from it. `tests/test_scripts.py:79-83` pins it only as the positive half of an isolation check. Direction: either document `RADD_URL` plus a token variable as part of the contract, or drop the line and the test's `url` key.
- **`ValidationBinding.mode` is stored per (trigger, target) row but derived per trigger since RADD-1329** (`service.py:703-705`). The "strictest per (automation, node)" merge in `validation.governing_graphs` (`:209-218`) is now moot. The dedupe is still needed.
- **`automation_schedule_max_items` is named for the deleted schedule `query`**, but it caps the search node (`search.py:105`).
- **`slas/__init__.py:96` — `SlaEvent.BREACHED` sits in trigger group "Items"**, while the other SLA events are in "Service desk".

## FLAG — C2 — notify, mailintake, pages, collab, attachments (backend)

Ranked by importance.

1. **BUG: `pages/service.py:913-928` (`drop_restricted_labelled`).** It reads `row.page_id`, but its rows come from `labels.pages_with_label` and are `PageLabelled` (`schemas.py:138-147`), which has `id` and no `page_id`.
   - Consequence: `GET /pages/by-label/{name}` (`router.py:477-490`) raises `AttributeError`, surfacing as a 500, whenever the label has at least one page in a readable space. That breaks the `radd:label-list` extension (`pages/ui/src/view/ListExtensions.tsx`).
   - Evidence: `uv run python -c "…PageLabelled(...).page_id"` raised `AttributeError: 'PageLabelled' object has no attribute 'page_id'`.
   - The code has been like this since `bd331dc2` [RADD-792]. The only test that mentions the route is `test_anonymous_surface.py:91`, an inventory check.
   - Fix: REDUNDANT 9, keyed on `id`, plus a test with a restricted page carrying the label.
   - About 2 lines to fix.
2. **`mailintake/models.py:62` (`MailContact.last_message_id`) is a write-only column.** `service.upsert_contact` writes it (174, 180), but no production code reads it. Threading moved to `mail_messages` (RADD-952), and the `models.py:81` docstring itself calls it the old mechanism.
   - Only tests read it: `test_mail_render.py:245`, `test_mail_threading.py:692-712`.
   - Direction: drop the column, the `message_id` parameter of `upsert_contact` and the two test assertions. Needs a migration.
   - About 15 lines plus a migration.
3. **Files that should split:**
   - `pages/service.py` (935 lines):
     - versions (`list_versions`, `get_version`, `write_version`, `restore_version`, `seal_history`, `_history_window_open`) → `versions.py`
     - archive and bulk (`archive_page`, `unarchive_page`, `hard_delete_page`, `bulk_*`, `_depths`) → `archive.py`
     - the restricted-row filters → `page_access.py`
   - `mailintake/intake.py` (920 lines):
     - sender authentication (`SenderAuth`, `_check_sender_auth`, `_sender_auth`) → `senderauth.py`
     - contacts (`_capture_contacts`, `_touch_contact`, `_is_ours`, `_is_real`) → `contacts.py`
     - files (`_store_attachments`, `_note_dropped_attachments`, `_retain_raw`) → `inbound_files.py`
   - `mailintake/transport.py` (592 lines): the mail-health half (515-592) → `health.py`.
   - `pages/router.py` (596 lines): templates (227-296) and versions (533-555) → sub-routers.
   - `notify/consumer.py` (529 lines): `_allowed` → `gate.py`.
   - `mailintake/types.py` (477 lines): presets (113-214) → `presets.py`.
   - `notify/service.py` (517 lines): the rules half (309-517) → `rules_store.py`.
4. **`collab/channel.py:70-83`: every OUTBOUND frame calls `_revalidate()`.** That opens a DB session and runs `resolve_session_users` plus `page_access.guard_page`, which walks the ancestor path and loads grants, per frame per client. One keystroke broadcast to N clients therefore costs N permission resolutions.
   - Inbound frames are throttled by `collab_frame_auth_seconds`; outbound frames are not.
   - Direction: apply the same throttle to `send`. The docstring's "before every outbound frame" would then describe a throttle.
   - About 3 lines.
5. **`minio` is a core dependency** (`server/pyproject.toml:18`) whose only use is `attachments/clients.S3Client`.
   - The MinIO server's community edition was archived in Feb 2026 (`docs/deploy.md:164`), and Garage is the blessed server.
   - Direction: either make it an actual `radd[s3]` extra, which is what the stale comment claims, or replace it with a maintained S3 client. The client already notes that presigning is pure HMAC.
6. **Reserved states that nothing reaches:**
   - `attachments/types.py:45` `AttachmentState.PENDING` is "reserved: presigned-PUT direct upload (designed, deferred)". Every `state == STORED` filter (`email_export.py:66`, `ai/images.py:81`) is therefore always true.
   - `MoveJobState.CANCELED` (`types.py:74`) has no cancel path, yet the UI renders a "Canceled" label (`web/src/components/settings/storage/MoveJobProgress.tsx:25,43`).
   - Direction: drop them until built, or build the cancel path.
7. **`mailintake/types.py:387` `MAIL_RAW_RETENTION_DAYS = 30`** is only ever tested `<= 0` (`intake.py:750`). The 30 is read by nothing, and the comment promises "a retention SWEEP … is a separate follow-up; this constant is what it will read".
   - Direction: make it a bool (`MAIL_RAW_RETENTION = True`) or build the sweep.
8. **`docs/modules.md` has drifted from the code:**
   - Line 194 describes `DEFAULT_MATRIX` as a constant and `types.DEFAULT_EMAIL_TYPES` as "the migration's and DEFAULT_MATRIX's definition". It is now `rules.default_matrix()` built from `kinds.default_channel`, and the migration does not import notify.
   - Line 197 calls `attachments.gc` an "orphan-GC consumer"; it is a kernel cascade (RADD-745).
   - Line 204 still documents `GET /public/pages/*` and `pages_by_ids`' `public_only` re-check as live. Line 284 of the same file says they are deleted (RADD-1147).
9. **Naming left over from the docs/wiki/kb rename (RADD-701), outside comments.** These are schema and function names only, not wire contracts; no SPA reference was found (`git grep -E 'DocSearchResult|DocLinkCreate|DocRestoreRequest|search_docs|item_docs' -- web`).
   - `pages/schemas.py:285,292,321`: `DocRestoreRequest`, `DocLinkCreate`, `DocSearchResult`. These appear in the OpenAPI component names.
   - `pages/types.py:8`: `DOCS_TS_CONFIG`.
   - `pages/router.py:382,586`: `search_docs`, `item_docs`. These appear in the OpenAPI operationIds.
   - Outside this scope: the `ai/embeddings/embedder.py:185,210` alias `docs_search`, and `_embed_docs`.
   - No `doc_page` entity key, `/docs/search` route or `kb` symbol remains in scope. The only mentions are in comments (TRIM).
10. **`pages/export.py:143-151` (`by_last`)** maps a bare slug to the one exported page carrying it, "like the resolver's last-segment fallback". `paths.py:17-21` says the resolver has no such step; old single-slug addresses resolve through `page_path_history`.
    - Direction: decide whether exports keep this pre-1233 mapping (it works offline), and fix the justification either way.
    - About 9 lines at stake.
11. **Legacy compatibility against the "no backcompat until V1" rule:** `attachments/service.py:308-314,324-327` treats `host_id=None` as "a pre-102 row, means the default host", for `remove_blob` and `read_blob`.
    - Direction: if every stored blob ref now carries a host (jiraimport, mail raw), backfill and make `host_id` required.
    - About 6 lines.
12. **Minor mislabelled `NotFoundError` entities:**
    - `mailintake/rules_router.py:107` uses `MailEntity.MAIL` for a missing rule; it should be `MailEntity.RULE`.
    - `pages/router.py:280` uses `PageEntity.PAGE` for a missing template.
13. **The same "full ordered list → positions, one audit row per moved rule" reorder** is implemented twice: `mailintake/rules_router.py:131-155` and `attachments/routing/store.py:117-140`. Cross-module; a kernel helper would serve both. About 10 lines.
14. **`notify/mailer.py`: a comment mail reads its `comment.created` event twice** (`_comment_body` → `_comment_id`, then `_send:293` → `_comment_id` again). This is an efficiency issue, not bloat.

## FLAG — D1 — jiraimport, confluenceimport, ldap, sso (backend)

- **F1 — Jira attachments and change history are downloaded but never imported.**
  - `PlanOptions.import_attachments` and `import_history` (`plan/schemas.py:144-145`) are shown as toggles (`ui/src/PlanParts.tsx:82-83`), and nothing on the server reads them (`git grep -n 'import_attachments\|import_history'` finds only the schema).
  - `RunStage.ATTACHMENTS`/`HISTORY` are never set, `ItemDraft.attachment_ids` is never read, `LedgerEntity.ATTACHMENT` is never recorded, and `markup._image` degrades every `!file.png!` to "*(image: …)*".
  - Meanwhile the download side (`include_attachments`/`include_history`) pushes binaries into the object store and backfills changelogs. That is ≈ 215 lines:
    - `snapshot/download.py:391-528`;
    - `client.fetch_binary`/`issue_changelog`;
    - the `JiraSnapshotBlob` model and store helpers;
    - the storage-host use check (`__init__.py:21-23`);
    - the blob-removal loop (`snapshot/service.py:65-73`).
  - **Direction:** decide. Either build the import side (≈ 120 lines, using `confluenceimport/runs.py:421-501` as the template), or delete the download side and the four toggles.

- **F2 — UI options the server silently ignores.**
  - The field-mapping "Map to feature" menu offers Status/State, Assignee and Priority (`ui/src/FieldRow.tsx:26,29,32`). `issuemap._apply_native` decodes them into `native_status_name`, `assignee_email` and `priority`, but `transform.build` never reads those (`transform.py:210-221`). Picking one does nothing and reports nothing.
  - "Placeholder e-mail domain" (`ui/src/PlanEditor.tsx:187-191` → `PlanOptions.placeholder_email_domain`) flows to `provision.run(placeholder_domain=…)`, which ignores it (DELETE above). Placeholder addresses are fixed at plan creation from the connection-derived domain.
  - **Direction:** wire each into `transform`/`suggest`, or remove it from `BuiltinTarget`, the UI and the plan options. ≈ 20 server lines plus UI.

- **F3 — English-name heuristics that survived the spec-100 rebuild.**
  - `issuemap.LINK_TYPE_MAP` (still the fallback when a type is missing from the plan, `transform.py:255`).
  - `mapping._NATIVE_BY_NAME` (`"epic link"`, `"parent link"`, `"watchers"`; its three points entries duplicate `schemakeys.STORY_POINT_NAMES`).
  - The `"epic link"` name fallback in both `runs._epic_field` and `accumulate`.
  - `suggest._EPIC_HINTS` and `startswith("sub")`.
  - Some are defensible, for example DC Story Points has no schema key. **Direction:** put every name heuristic in `schemakeys`, with a stated reason each, and drop the duplicates. Separately, the unread OPTION_SETS catalog was the spec-90 "show every configured option" feature; deleting it (DELETE above) is the call unless the value tables should list unused options.

- **F4 — `radd/importkit` consolidation.** This is the REDUNDANT section's first entry, ≈ 530 lines. It is a design step rather than a mechanical cleanup: it gives the two optional plugins a shared library, and `docs/modules.md` needs the new node. Worth doing as its own issue.

- **F5 — The two importers cache bytes differently.**
  - Confluence moved snapshot bytes onto disk after pushing 49 GB through Garage made downloads crawl (`snapshot/package.py`).
  - Jira still pushes snapshot attachments through `attachments_service.save_blob` into the object store, and deletes them blob by blob (`snapshot/service.py:65-73`).
  - **Direction:** one policy, most naturally in importkit.

- **F6 — Lifecycle inconsistencies between the importers.**
  - Confluence `delete_snapshot` (`snapshot/service.py:98-106`) deletes a snapshot mid-download; Jira refuses with 409 (`snapshot/service.py:60-64`) because the running task inserts against a vanished parent.
  - Confluence's snapshot `mark_interrupted` does not set `finished_at`. Jira's run and snapshot `mark_interrupted` record no reason at all, which is the exact failure the Confluence version's docstring describes.
  - Jira `cancel_run` does not treat CANCELED as terminal.

- **F7 — Confluence rollback and ledger bugs.**
  - `runs.py:208-211` records **the page id** as the GRANT ledger `entity_id`, so rollback's `DELETE FROM access_grants WHERE id = <page id>` removes nothing and imported restriction grants outlive the rollback.
  - `_nearest_imported` (`runs.py:293-299`) claims to attach to the nearest imported ancestor but checks only the direct parent, flattening deeper gaps to the space root.
  - `_restore` lacks Jira's JSONB cast.

- **F8 — Rollback bypasses module ownership.**
  - Both rollbacks issue raw `DELETE`/`UPDATE` against other modules' tables: `work_items`, `comments`, `worklogs`, `users`, `field_definitions`, `pages`, `access_grants`, … (`jiraimport/rollback.py:38-54,201-229`, `confluenceimport/rollback.py:25-32,138-157`).
  - This contradicts rule 1 and leaves derived state (search index, backlinks, mentions) behind. Jira already delegates project teardown to `projects_service.delete_project`.
  - **Direction:** per-owner purge hooks keyed by entity type.

- **F9 — Credentials stored in plaintext; the docstrings are out of date.**
  - `JiraConnection`/`ConfluenceConnection` say "encrypt at rest when the secrets layer lands" and cite the webhook-secret precedent. That layer landed (`radd/secretbox.py`, RADD-1086), and webhook secrets are now encrypted (`webhooks/models.py:16`).
  - Still plaintext: Jira/Confluence `credential`, `sso_providers.client_secret` and the `ldap_bind_password` setting.
  - **Direction:** adopt secretbox (lazy, prefix-tagged, same as webhooks) and fix the docstrings.

- **F10 — LDAP login demotes admins when no admin groups are configured.**
  - `ldap/service.provision` sets `user.instance_role` on every login (`service.py:388-389`), even when `ldap_admin_groups` is empty.
  - The setting's own description says "Empty = the directory carries no role opinion (the spec-110 rule)" (`__init__.py:89-91`), and SSO implements exactly that (`sso/service._syncs_roles`).
  - As written, an instance admin who signs in through AD with no admin groups configured is demoted to member.
  - `server/tests/test_ldap.py` has no test for it.

- **F11 — Env "SEED-ONLY" paths.**
  - Candidates: `jiraimport.connections.seed_from_env` + `_seed_name` (≈ 45 lines), the same pair in confluenceimport (≈ 45), and `sso.registry.seed_from_env/_seed_provider/_env_domains/_seed_name` (≈ 55).
  - Settings behind them: `config.py` has 7 `jira_*`, 7 `confluence_*` and 8 `oidc_*` settings (the `*_timeout_seconds` and `*_placeholder_email_domain` ones stay live).
  - Each seed runs only on an empty table. Confluence was born DB-backed, so its seed never migrated anyone, and nothing in `deploy/`, compose, the dev stack or tests sets `RADD_CONFLUENCE_*`.
  - Per "no backcompat until V1", deleting all three is ≈ 150 lines plus config, the `docs/deploy.md:444` row and the `test_jira_connections.py:180-230` seed tests.
  - **Caveats:** the company deploy may seed Jira/OIDC from env; check `deploy.sh` first. And `sso` must keep a startup `registry.refresh_snapshot` (`seed_from_env` doubles as it; `test_capabilities.py:51` relies on it).

- **F12 — Files past the ~300-line rule, with their seams.**
  - `confluenceimport/storage/convert.py` (715): JQL→SLQ `648-715` → `storage/jql.py`; macro rendering `459-646` → `storage/macro_render.py`.
  - `confluenceimport/runs.py` (695): the attachment/reconvert/comment/history stages `421-597` → `run_stages.py`.
  - `jiraimport/runs.py` (669): `_pipeline` alone is 183 lines (115-297); split into `runs/vocab.py` (`_cycles`/`_releases`), `runs/refs.py` (`_parents`/`_links`/`_resolve`) and the driver.
  - `jiraimport/snapshot/download.py` (619): Jira fetchers `123-197` / stages / job.
  - `jiraimport/issuemap.py` (619): about 520 after the dead-code removal. Value rendering (`_scalar`, `render_value`, `_points`) and sprint-bean parsing are separate modules.
  - `jiraimport/provision.py` (580): one provisioner per entity once `_states`/`_issue_types` merge.
  - `confluenceimport/snapshot/download.py` (580); `confluenceimport/client.py` (451).
  - `jiraimport/types.py` (444): wire enums vs `InferredField`/`JiraCreds` value objects.
  - `ldap/service.py` (402): login bind vs directory enumeration vs provisioning.
  - `sso/service.py` (366) and `sso/registry.py` (364) are borderline.

- **F13 — Legacy paths outside the plugins.** These are outside this area, but they are the reason some plugin code exists.
  - `server/scripts/import_jira.py` (645 lines) is a second Jira importer, working over REST from sample JSON. With the `scripts/jira_markup.py` shim, it is why `jiraimport/markup.replace_attachment_embeds` exists; CLAUDE.md and README document it for sample data.
  - `server/scripts/import_ad_users.py` (110) is superseded by the in-app import plus user sync. It checks `bind_account_enabled()` without `refresh_conn`, so a DB-configured bind account (RADD-846) is invisible to it. Its docstring ("the one place a bind account is used") is false.

- **F14 — `docs/modules.md` has drifted.**
  - Line 288 (the jiraimport row) is 13 KB and describes files, endpoints and tables that do not exist: `runner.py`, `POST /jira/plans/suggest`, `jira_import_plans`/`jira_import_runs`, `_create_issue`, `ImportRunRead.field_mappings`, `RADD_JIRA_PAGE_SIZE`. It also calls spec 100 "in progress".
  - Line 203 (the ldap row) says "**NO tables**", but `directory_sync_state` exists (`ldap/models.py`).

- **F15 — A safety net that does not exist.** `storage/macros.py:22-26` promises a test asserting every extension name is registered, and there is none. `plan.validate_plan` checks EXTENSION rows only at plan time; the built-in table (including the `"new-from-template"` literal at line 177) is unchecked.

- **F16 — Jira download keep-alive is half-real.** The module docstring claims one `JiraClient` for the whole download. In fact `_search_page` opens a new client per ISSUES page, and `_fetch_children`/`_fetch_blobs` one per batch of 25/10. Either hold one client in `execute` (the importkit client base makes that easy) or fix the claim.

- **F17 — `except ImportError` used as a guard.** `jiraimport/apply.py:34-45` `_not_intake()` guards the optional `automations` module this way, which CLAUDE.md rule 1 says is never a guard. `alertmanager` and `mailintake` import `automations.intake.suppressed` unconditionally. Pick one pattern (a kernel socket or hook would suit rule 1).

- **F18 — Unimported Jira keys never link out.** `confluenceimport/runs.py:287` always passes `jira_base_url=""`, so `convert.jira_macro` degrades an unimported key to bare text in production; the external-link branch is reachable only from tests. The base URL could come from a Jira connection.

- **F19 — Redundant run columns.** `jira_runs` and `confluence_runs` each store both `kind` and a `dry_run` boolean. `dry_run` is `kind == dry_run` in Jira, and Confluence has no dry-run kind at all. Which is authoritative is a schema decision (migration).

- **F20 — LDAP import re-enumerates the whole directory.** `ldap/router._selected_directory_users` (136-149) enumerates the entire directory to find N selected e-mails, twice per import flow (preview, then import). A per-email filter would do.

- **F21 — Spec-40 backcompat branch in SSO login.** `sso/router._resolve_provider` (47-61) keeps a "no provider_id" branch for spec-40 bare `/auth/oidc/login` links. The SPA always passes `provider.id` (`web/src/components/SsoButtons.tsx:69`). Removing it is ≈ 4 lines; it is only worth doing as part of F11.

## FLAG — D2 — ai, vcs, gitlab, github, forgejo, alertmanager (backend)

- **F1 (bug) — `server/src/radd/modules/ai/automation_context.py:166-178`:** `_worklog_line` always returns "not tracked".
  - It calls `timelogging.item_summary(session, item_id, read.project_id)`, passing a UUID where the signature takes a project object. `timelogging/service.py:518-529` reads `project.id`, so it raises AttributeError, which is swallowed.
  - Even when that call works, it reads `summary.total_seconds`; `ItemTimeSummary` has `logged_seconds` (`timelogging/schemas.py:141-150`).
  - Result: the "Logged time" checkbox on `ai.classify`, `ai.validate` and `ai.generate` has never produced data, and nothing tests it (`git grep "not tracked\|_worklog_line" server/tests` finds nothing).
  - Direction: reuse `summarize._worklog_digest` (REDUNDANT 24) and add a test. ~8 lines.
- **F2 (bug) — `server/src/radd/modules/ai/admin_router.py:102-104`:** the provider Test button builds `ResolvedModel(wire_shape, base_url, api_key, model)` without `reasoning` or `request_params`.
  - So every probe sends reasoning OFF (`chat_template_kwargs.enable_thinking=false`) and none of the admin's extra parameters.
  - `provider.with_reasoning`'s docstring (`provider.py:139-142`) says api.openai.com rejects that key "which the Test button surfaces — such a provider sets reasoning ON". With this code the Test keeps failing after the admin does exactly that.
  - Direction: `registry.resolved_from_row(row, model)`, used by both `resolve_role` and the probe. This also merges their two copies of the LOCAL default-model block (`registry.py:336-342`, `admin_router.py:95-99`).
- **F3 — `server/src/radd/modules/ai/admin_router.py:136-138`:** `EmbeddingCoverage(..., last_error=embedder.last_error())`, but the model (`:112-117`) has no `last_error` field. Pydantic ignores it, and `ui/src/EmbeddingHealthCard.tsx:5-11` doesn't read it either.
  - RADD-723's "say WHY coverage is zero" never reaches anyone.
  - Direction: add the field and render it, or delete the `_last_error` bookkeeping (`embeddings/embedder.py:112-151`, ~15 lines). Recommend adding it.
- **F4 — `server/src/radd/modules/ai/registry.py:460-471`:** `seed_from_env` seeds whenever `ai_providers` is empty. If an admin deletes every provider while `RADD_AI_PROVIDER` is still set, the env row comes back on the next boot, and the docstring claims the opposite.
  - The connectors (`vcs_seeds`) and alertmanager (`alertmanager_seed`) fixed this with a claim table.
  - Direction: one shared `claim_env_seed(name)` (REDUNDANT 14).
- **F5 — `server/src/radd/modules/ai/registry.py:161-165`:** `update_provider` accepts `wire_shape → local` without `_validate_local_shape` and without checking held roles. A provider holding the chat role can become LOCAL, which makes the "unreachable" hard stop in `client._completion_payload:36-39` reachable, and its comment wrong. Mirror `set_role`'s checks on the shape change.
- **F6 — Forgejo PR `ref_type` flips:** the webhook plans `VcsRefType.MERGE_REQUEST` (`forgejo/parsing.py:102`, pinned by `tests/test_connectors.py:119`), while the backfill writes `PULL_REQUEST` (`forgejo/backfill.py:202`) for the same `pr:` external id. `upsert_vcs_link` rewrites `ref_type` on every re-delivery (`vcs/service.py:106`). GitHub uses PULL_REQUEST on both paths. Pick one.
- **F7 — oversized files:**
  - `server/src/radd/modules/ai/registry.py` (504 lines) splits into `providers.py` (CRUD + emit + local-shape checks), `roles.py` (set/clear/resolve/audit), `presets.py`, and snapshot + seed.
  - `ai/types.py` (308 lines) mixes enums and constants with API schemas; `schemas.py:1` even says the spec-46 schemas "stay in types.py". Move the pydantic models (`AiStatus`…`NlQueryResponse`, `types.py:194-308`) to `schemas.py`.
  - The connector `service.py`/`admin_router.py`/`backfill.py` files (250-370 lines each) are resolved by REDUNDANT 1-6.
- **F8 — one AI feature is spelled in 5 places:** `AiFeature`, `FEATURE_ROLE`, `FEATURE_SETTING`, a `SettingSpec` in `ai/__init__.py`, `SettingKey.AI_*` in CORE `settings/types.py:122-132`, plus `config.ai_*`.
  - The core settings enum naming an optional plugin's keys cuts against plugin ownership (RADD-1343). `mailintake/signature_router.py:20,40` reads `SettingKey.AI_MAIL_SIGNATURE` too.
  - Direction: ai-owned key constants derived from one `AiFeatureSpec` table. Out of this scope's files.
- **F9 — `server/src/radd/modules/vcs/service.py:243-245`:** a backcompat shim that reads legacy `ci_run_id`/`ci_state` into `ci_reports` for rows written before migration `d1334review_execution_and_vcs_scope`, which added `ci_reports` with no backfill.
  - Per the no-backcompat-until-V1 rule: backfill it in a migration and drop the shim. 3 lines.
  - `uq_item_vcs_links_legacy_ref` is NOT legacy; see Not bloat.
- **F10 — docs drift, outside this scope:** the `docs/modules.md` ai row is one ~1,400-word table cell. It still describes `ai.validate` with `ctx.add_finding` and `on_unavailable: fail` (replaced in RADD-1329 by ports + `publish_findings`) and says "Seven feature toggles" (there are 10 features plus stream_responses).
- **F11 — cosmetic imports:** `ai/__init__.py:90-92` (`# noqa: E402` imports after function defs) and `vcs/__init__.py:10` (a separate `from .types import VcsEntity  # noqa: E402`). Merge them into the top import block.
- **F12 — plugin `description=`:** GitHub's `description=` (`github/__init__.py:28`) omits the `/spend` time mirroring, and Forgejo's (`forgejo/__init__.py:31`) omits tracked-time mirroring. GitLab's mentions it. Align them.

## FLAG — E1 — host components (incl. the roadmap part)

- **`editor/RichEditor.tsx` (1,037 lines, 257 of them comments).** Three natural seams:
  1. The mention/quick-action popup, about 150 lines: `candidates` (`:522-552`), `accept`, the store handlers (`:556-600`), `popupHint` (`:849-861`) and the portal list (`:995-1034`). Move them to `useMentionPopup` plus `MentionPopup.tsx`.
  2. The transform/review orchestration, about 120 lines: `dispatchTransform`, `navigateReview`, the review-end effect, and the `detached`/`notes`/`current` state. Move these to `useTransformReview(editorRef)`.
  3. The create effect (`:602-831`), about 230 lines: move it to `useMilkdownEditor(options)`. The component then becomes chrome only.
- **Other files over the size threshold:**
  - `CommandPalette.tsx` (615): the one function spans `:109-561`. Seam: entry assembly (gotos, search, entity hits, modes) into `usePaletteEntries(query, mode)`, and the rows (`AnswerRow`, `PaletteRow`, `SectionLabel`) into `PaletteRows.tsx`.
  - `items/NewItemModal.tsx` (670): split out the verdict handling (see REDUNDANT) and the optional-field `place()`/secondary section into `NewItemOptionalFields.tsx`.
  - `items/IssueProperties.tsx` (643): move the pickers (`TypePicker`, `PointsField`, `peopleOptions`, the person pickers, `TeamPicker`, `:443-643`, about 200 lines) to `IssuePropertyPickers.tsx`.
  - `Select.tsx` (480) is one component; leave it.
- **Two parallel schema-to-form implementations.** `editor/extension-schema.ts`, `ExtensionConfig.tsx`'s `Field` and `ExtensionPicker.defaultsFor` overlap the SDK's `SchemaForm`/`defaultsFromSchema` (`web/packages/plugin-sdk/src/schema-form.tsx`, `schema-defaults.ts`). The extension flavour adds `markdown` fields, default omission and unknown-key carry-through. Consider growing the SDK form rather than keeping a second renderer. About 150 lines at stake. It is not mechanical.
- **Cells render in two places, and they disagree.** `views/ColumnCells.tsx:220-321` (`CellContent`) and `board/card-cells.tsx:111-256` (`renderCardCell`) both map attribute id to chip. The presentation differences are deliberate, but the two already disagree on content:
  - `logged_time` goes through `formatDuration(…, durations)` on the list (it honours the duration config) but through `formatSeconds` on the card;
  - `visibility` exists only on cards.
  A shared "value or empty" table per attribute, with a surface renderer on top, would keep new attributes in sync.
- **Escape handling bypasses `lib/dismiss-stack.ts`.** `ContextMenu.tsx`, `DropdownMenu.tsx`, `items/SimilarHoverCard.tsx:69-81`, `CommandPalette.tsx`, `views/SlqEditor.tsx`, `views/QueryBar.tsx`, `views/ViewList.tsx`, `roadmap/LinkPopover.tsx`, `roadmap/UnscheduledTray.tsx` and `roadmap/RoadmapSurface.tsx` each attach their own Escape listener. Only `Modal`, `Popover`, `IssuePanel` and `Sidebar` register with the dismiss stack. That stack exists because independent listeners close two layers per Esc.
- **Hand-rolled kit pieces:**
  - `items/CommentsThread.tsx:447-507` (`CommentActions`) has an inline "Confirm delete / Keep" pair instead of `useConfirm` (also `routes/settings/roles.tsx:345` and `routes/view.tsx:1098`, outside scope).
  - `items/TimeTrackingPanel.tsx:419-427` deletes a worklog with no confirm at all.
  - `items/IssueProperties.tsx:394-416` (`MoreFields`) and `:425-441` (`TimeTrackingSection` header) re-draw the SDK `CollapsibleCard` header. `MoreFields` sits inside a divided card, so it is not a drop-in; consider a headless `useCollapsible`/`CollapsibleHeader` in the SDK.
- **The same worklog entry is drawn twice.** `items/WorklogTab.tsx:36-56` (read-only) and `items/TimeTrackingPanel.tsx:396-432` (`WorklogRow` read mode) render one entry in two layouts. Give `WorklogList` a `readOnly` mode and let the tab reuse it (about 25 lines).
- **Two CodeMirror setups.** `CodeEditor.tsx` and `editor/code-block.ts` build near-identical base extension lists and language loading. `plugin-boundaries.test.mjs:120-127` forbids `CodeEditor.tsx` from importing `components/editor/`, so a shared `lib/codemirror-base.ts` is the place.
- **`editor/PlainEditor.tsx:247-258` acts on `onMouseDown`.** The rich toolbar's documented rule (`Toolbar.tsx:22-26`) is the opposite: act on click so the button is keyboard-reachable. The plain toolbar is mouse-only.
- **`items/CardSlots.tsx` is misnamed.** It holds only `isOverdue` (15 lines), which `card-cells.tsx` and `ColumnCells.tsx` use. Move it to `lib/` (for example `lib/view-utils.ts`), and fold in the inline copy at `routes/my-work.tsx:162`.
- **`KindBadge` has a stale fallback.** `items/ItemBadges.tsx:181-205` keeps an "undefined `kind`" placeholder "while the spec-02 backend hasn't landed". The cause is `kind?: ItemKindValue` in `lib/types/items.ts:115,159`, which is outside this scope. The fix is in the type.
- **`items/HistoryTab.tsx` has two smaller issues.**
  - It switches on about 30 raw event-type strings, against development rule 2 (enums).
  - It hand-draws an initials circle instead of `Avatar`.
  - Its csat/mail cases are pinned by `plugin-boundaries.test.mjs:565-567`. Keep those.
- **`editor/rich-editor.css:136-138` looks dead.** It sets `pointer-events: none` on `input[type="checkbox"]` in the viewer, but Milkdown's list-item-block draws `.label` spans, not inputs, and read-mode toggling (RADD-1296) is handled on those labels. Verify in a browser before deleting.
- **Two unrelated spinners share a name.** Host `Spinner.tsx` (a centred page loader, 41 importers) and SDK `Spinner` (inline) are different components.


### roadmap/ (helper agent)

_Paths in this subsection are relative to `web/src/components/roadmap/` unless they are spelled out in full._

1. `RoadmapSurface.tsx` (942 lines). Four natural seams, which leave ~350 lines:
   - **Toolbar JSX** 617-813 (~195) → `RoadmapToolbar.tsx`. With REDUNDANT 1 applied, ~130.
   - **Epic-children verbs** 308-441 (~135: `fetchEpicChildren`, `loadChildrenWithEstimates`, `withInserts`, `handleAutoSchedule`, `handleImportChildren`) → `useEpicChildVerbs.ts`.
   - **Navigation/selection** 491-615 (~125: viewport hook call, selection state, `frameSelection`, the keyboard handler, the today anchor). The frame and today-anchor parts belong beside `zoomBy` in `useRoadmapViewport.ts`, which already owns zoom; selection becomes `useRoadmapSelection`.
   - **Progress data** 254-306 (~50) → `useRoadmapProgress.ts`.

2. `RoadmapTimeline.tsx` (686 lines). Seams, leaving ~430:
   - hover-card dwell 203-275 (~73) → `useBarHoverCard.ts`;
   - rubber-band selection 373-427 (~55) → `useRubberBandSelect.ts`;
   - axis header 482-531 (~50) → `RoadmapAxis.tsx`;
   - `containerRegions` 320-360 (~40) → a pure function in `model/` (testable like the rest of the model).

3. `BarRow.tsx` (539 lines, 30 props). The label cell 219-354 (~135) is a self-contained component (`BarRowLabel`). It owns the HTML5 reorder drag, selection, collapse, solo and member toggles, and those props partition cleanly from the bar lane's 356-536. The solo and member toggle buttons (304-353) share one class recipe; a local `RowToggle` would dedupe them.

4. `useRoadmapEditing.ts` (472 lines). The link-popover state and handlers 313-385 (~73) → `useRoadmapLinks.ts`, and the collapse set 78-136 (~59) → `useCollapsedEpics(viewId)`. Together with REDUNDANT 4/5/9/10 and the trims, what remains is ~250.

5. `useBarDrag.ts` (382 lines). ~355 after the trims. Optional seam: the edge auto-scroll/extension effect 299-342 → `useEdgeAutoScroll`. Low priority.

6. **Auto-schedule records TWO draft ops, and its rank chain ignores `rankOrdered`.** `RoadmapSurface.tsx:398-409` pushes the patch op, then `applyRankChain` pushes a chain op labelled "Order N rows by date". One Undo reverts only the ordering, under a label that doesn't name auto-schedule. This contradicts useRoadmapDraft's "one auto-schedule … = one op". Unlike "Order children by date" (`RoadmapContextMenu.tsx:191`), the chain is not gated on `rankOrdered`, so on an explicit-ORDER-BY view it rewrites global ranks the rows don't follow. Direction: one compound op (or an undo group), plus the same gate.

7. **Magic literals** (CLAUDE.md rule 2):
   - the axis header height `40` appears in `RoadmapTimeline.tsx:492` and again in `RoadmapSurface.tsx:541` ("Rows start after the 40px axis header");
   - the zoom step `1.4` / `1 / 1.4` (`RoadmapSurface.tsx:640, 649`);
   - the minimum visible width `100` (`:528`);
   - the week-tick thinning `dayWidth < 8` / `% 14` (`RoadmapTimeline.tsx:301`).

   Direction: named constants in `lib/constants/roadmap.ts`.

8. **Roadmap tunables live in four homes:**
   - `lib/constants/roadmap.ts`;
   - `model/geometry.ts`;
   - locals in `useBarDrag.ts:52-57` (`DRAG_THRESHOLD_PX`, `AUTOSCROLL_PX_PER_FRAME`, `AUTOEXTEND_HOLD_MS`);
   - per-component card/popover sizes (`RoadmapHoverCard.tsx:28-32`, `LinkPopover.tsx:21`, `RoadmapTimeline.tsx:47`).

   Direction: interaction tunables in constants, pure geometry in `model/geometry.ts`.

9. **Raw palette utilities beside status tokens**:
   - `BarRow.tsx:419, 521` (`bg-red-500`, `bg-red-500/15 text-red-300`);
   - `RoadmapHoverCard.tsx:50, 53, 140` (`bg-emerald-500/80`, `bg-red-500`, `text-red-400`);
   - `LinkPopover.tsx:124` (`border-red-500/40 … text-red-400`);
   - `RoadmapSurface.tsx:758` (`border-amber-500/40 bg-amber-500/10`).

   Meanwhile `Connectors.tsx` uses `var(--status-danger)` / `var(--status-warning)`, and the kit uses `status-danger-ink`. Not banned (the ban names zinc/indigo), but it is the same inconsistency RADD-900 fixed for the SVG.

10. **Link types are hardcoded while spec 91 made them data**:
    - `LinkPopover.tsx:14-19` offers only Blocks/Relates/Duplicates;
    - `RoadmapContextMenu.tsx:65-69` maps every non-blocks/non-duplicates type to "relates";
    - `Connectors.tsx:143-145` colours every non-blocks type neutral.

    A user-defined link type (`item_link_types`, with `outward_name`/`inward_name` in `server/src/radd/modules/linktypes/models.py:20-22`) cannot be created from the roadmap and reads as "relates" in its menu. Direction: read the link-type catalog. Beyond bloat, but it is why REDUNDANT 12 should use data rather than `LINK_GROUP_LABELS`.

11. **SLQ string quoting three ways.** `UnscheduledTray.tsx:29` hand-rolls `slqString`, while the other `title ~` builders use `JSON.stringify` (`lib/planning-query.ts:50`, `lib/usePlanningSectionSearch.ts:32`, `routes/starred.tsx:38`), and `routes/project-releases.tsx:398` escapes only quotes. Direction: one `slqString` in `lib/slq.ts`.

12. **Cross-scope drift found from here** (outside this sub-scope; routing to the coordinator):
    - `web/src/lib/constants/roadmap.ts:5`: a stale first docstring stacked above the real one for `ROADMAP_LABEL_WIDTH`.
    - `:36-37` says the leaf span "also paces 'Bring children into roadmap' (each child gets a week-long bar)". Import uses `ROADMAP_IMPORT_SPAN_DAYS = 1`.
    - `web/src/lib/item-mutations.ts:144-153`: the `useRoadmapItemPatch` doc still describes a per-gesture optimistic unit with rollback; only `saveDraft` calls it now.
    - `useAddItemLink(_projectId)` / `useRemoveItemLink(_projectId)` (`item-mutations.ts:329, 341`) take an ignored parameter, which the roadmap fills with `""` (`useRoadmapEditing.ts:102-103`).
    - `docs/modules.md:304`'s spec-19/77/78 paragraph describes "one optimistic unit" commits and the "unscheduled split". Both are superseded by the draft wave and the tray's own query.

## FLAG — E2 — host lib, routes, settings, shell, root

- `web/src/routes/view.tsx` (1,470 lines; `ViewPage` spans 113–~1417) — the page is one function holding ~45 `useState`/`useQuery`s. Seams: `useViewQueryComposition` (quick/personal chips + bar → `effectiveView`, 147–221), `useRoadmapScope` (planning options, show-closed/epics-only/members, `fetchQueryView`, 223–339), `useViewPaging` (page state, counts, roadmap auto-stream, tray query, `items` assembly, 370–461), `useViewDisplay` (columns, card layout, attribute/rollup/timelog batches, 463–555), `useViewMutations` (WIP, columns, bucket order, card layout, 589–620), selection + bulk (581–588, 768–830), and the JSX as `ViewHeader` (841–1173) and `ViewSurface` (1180–1330). `SaveFilterButton` (1419+) to `components/views`. — ~1,400 lines to redistribute, no net change.
- `web/src/components/settings/TransitionsSection.tsx` (1,008 lines) — seams: condition model (types, `customChoice`, `opLabel`, rules rebuild; 31–183) → `transitions/model.ts`; `TransitionsSection` + `ModeSetting` (184–334); `TransitionRow` (335–545); the condition builder `ConditionListEditor`/`ConditionRow`/`ConditionValues` (546–912, 367 lines) → `transitions/ConditionBuilder.tsx`; `UnservedRules` + `AddTransitionForm` (913–1008).
- `web/src/components/shell/Sidebar.tsx` (585 lines) — the Dashboards section (321–367) is hand-written host code importing `@radd-plugin-ui/dashboards/sidebar`, while the Pages section (380–382) is a `sidebar.section` contribution — the same core-plugin situation handled two ways. Make Dashboards a `sidebar.section` contribution like Pages. Also extract `SidebarProjectsSection` (416–518) and `SidebarCyclesSection` (384–414). — ~45 lines leave the shell.
- `web/src/components/shell/PinsBar.tsx:55-67` — `LINK_ICONS` maps `"/docs"`, a prefix no route has had since the wiki moved to `/pages` (spec 124; `PageRoute.pages = "/pages"`), so a pinned wiki page falls to the generic `Link2` icon. Evidence: `git grep -n '"/docs'` → `PinsBar.tsx:60` only. Fix: `"/pages"`. (A one-line bug, not dead code.) Also `PinsBar.tsx:252-281` `NewPageButton` is wiki-specific shell code reaching into `@radd-plugin-ui/pages/{endpoints,queries,types}`; a contributed "new" action would let the pages plugin own it.
- `web/src/components/shell/TopBar.tsx:66` — the palette pill reads "Search issues, docs — or ask…"; Ask is the ai plugin's contributed palette mode (RADD-1400), so with ai disabled the shell advertises a mode that is not there. Derive the hint from the registered palette modes.
- `web/src/routes/roadmap.tsx` + `router.tsx:279-280` + `constants/routes.ts:78-79` — all three call the `/p/$key/roadmap` route "LEGACY … so old links keep working", but `components/CommandPalette.tsx:221` links every project's "Roadmap" goto to it, so it is a live resolver. Either reword the three comments or point the palette at the project's roadmap view directly and then delete the route (then it would be DELETE, ~50 lines).
- `server/src/radd/modules/releases/__init__.py:18` — `EntityLinkSpec('release', ('/p/{project.key}/settings/releases',))` still points the audit ledger at the old settings address, which is why `ProjectReleasesSettings` (`routes/project-settings/layout.tsx:162-166`), its route (`router.tsx:623-627,687`), its lazy import (:43) and `ProjectSettingsSection.releases` must stay. Pointing the spec at `/p/{project.key}/releases` lets ~12 host lines go (and `web/scripts/usability-audit-proof.mjs:148`).
- `web/src/router.tsx:18` — `ProjectReleasesPage` (423 lines) is imported eagerly into the main chunk while every other page is `lazyRouteComponent`. Make it lazy.
- `web/src/routes/item-detail.tsx` is not a route: it exports `ItemDetailBody`, imported by `routes/item-page.tsx` and `components/items/IssuePanel.tsx`. Move it to `components/items/`. Likewise `routes/view.tsx:100` imports `CycleModal` from `routes/settings/cycles.tsx` — move `CycleModal` to `components/cycles/`.
- `web/src/lib/queries/shared.ts:7` states "never inline key arrays elsewhere", but many factories inline keys (`["groups"]`, `["groups", id, "reach"]` in `queries/users.ts:255,281`; `["child-item-cursors", …]` in `queries/items.ts:103`; `["comments", parentType, parentId]` in `host-documents.tsx:56`; `[...queryKeys.teams, teamId, "groups", …]`). Either register them or drop the rule.
- Other files over ~300 lines (seams only where obvious): `routes/timesheet.tsx` 668, `routes/settings/backups.tsx` 636 (status / schedules / artifacts are three cards → three files), `routes/item-detail.tsx` 572, `routes/project-settings/states.tsx` 570 (the category-vocabulary editor at 322+ is its own component), `lib/meta.ts` 525 (VCS/link/web-link visuals 327–525 vs enum display tables), `lib/hooks.ts` 522 (auth, peek, permissions, SLQ probe, item-by-key — five concerns; `SlqProbe*` belongs with `slq-filter.ts`), `lib/view-utils.ts` 491, `routes/settings/users.tsx` 478, `lib/item-mutations.ts` 452, `routes/project-releases.tsx` 423, `components/settings/AccessInspector.tsx` 408, `routes/settings/cycles.tsx` 405, `routes/settings/layout.tsx` 397 (the nav table 76–244 could be its own module).

## FLAG — F — plugin SDK + the six largest plugin UIs

### Correctness findings (not bloat, but found on the way)

- **automations — `GraphInspector.tsx:111-113 hasCoreEditor` returns true for any `action.*` key.**
  - A future contributed `action.<x>` renders no form (`ActionParams` `default: return null`) and never offers its `automation.node.inspector` slot.
  - `ActionsBuilder.tsx:119-120 default: return false` then marks it incomplete forever, and `RuleEditor.tsx:90-91` blocks Save.
  - Related: core still carries the forms for two optional plugins' actions, about 80 lines:
    - `ActionParams.tsx:361-371, 451-452, 507-559` (`SendEmailParams`);
    - `ActionsBuilder.tsx:104-106, 117-118`;
    - `types.ts:214-222` (`EmailRecipient`);
    - `automation-nodes.ts:205-233` (`EMAIL_ROLES`, the `send_email` branch).
  - The backend moved `action.send_email` to mailintake and `action.add_participant` to participants in RADD-1387 (`mailintake/__init__.py:29`, `participants/__init__.py:54`, `automations/types.py:120-123`), but `types.ts:177-211` still calls itself the backend mirror.
  - Direction: mailintake and participants register `automation.node.inspector`; `hasCoreEditor` tests the built-in set; unknown actions count as valid and the server's 422 decides.
- **pages — "print with subpages" order differs from the tree** (REDUNDANT #2: the unsorted `descendants` in `PagePrintPage.tsx:168-184`).
- **pages — `view/IncludedPage.tsx:85-87`: the "you do not have access" branch can never fire.**
  - It tests `error.message.includes("403")`, but `ApiError.message` is the server's `detail` (`plugin-sdk/src/api.ts:13`), and `ForbiddenError` always carries one (`server/src/radd/exceptions.py:34-37`).
  - A restricted page also answers 404 (`pages/router.py:358-363`).
  - Direction: `error instanceof ApiError && error.status === 403`, or drop the branch. 3 lines.
- **pages — `view/ChangeUrlDialog.tsx:28-34` says old-slug links stop working.** Since RADD-1233/1234, every old address resolves through `page_path_history`. The `/pages/{spaceSlug}/` prefix it previews also omits the parent path. Direction: reword the copy and show `pageHref(spaceSlug, parentPath)`. ~5 lines.
- **pages — `view/PublicBadge.tsx`: a stale tooltip ("Readable without login at /kb", spec 74, deleted by RADD-1147) and raw `bg-emerald-500/15 text-emerald-300`.** 3 lines.
- **automations — `RuleCreate`/`RuleUpdate` types have drifted from what is sent.** `RuleEditor.tsx:95-106` sends `note` (and `adopt_execution` on create), which neither type declares. `payload satisfies RuleUpdate` does not catch this because `payload` is a variable, not a literal.
- **automations — the served catalog carries 3 fields no client reads**: `manual_trigger`, `schedule_trigger`, `schedule_kinds` (`automations/schemas.py:763-766`, `router.py:106`, `types.ts:157-160`). `trigger_kinds` (RADD-1323) superseded them. They appear only in 4 proof fixtures (`browser-automation-canvas.mjs:15`, `browser-plugin-availability.mjs:35`, `browser-query-contributions.mjs:13`, `browser-schedule-contributions.mjs:17`). Drop them server-side, in TS and in the fixtures together.
- **Test gap — `web/scripts/plugin-boundaries.test.mjs:207` sets `const ast = owner === "automations" ? [] : …`**, so the "imports only the SDK and schedule-contract" assertions check nothing for automations.
- **ai — the popover's "Summarize issue" ignores `stream_responses`, and its similar list never streams rerank reasons** (REDUNDANT, `ReadMenu`).
- **dashboards — My Work may draw each personal widget's heading twice** (`WidgetGrid.tsx:59` `nameOf(widget)` plus the host's `routes/my-work.tsx:58` `ListSection` title). Not verified in a render; worth one screenshot.

### Cross-cutting

- **SDK kit gaps.** Each pass found a helper that plugins re-implement because only the SDK can share code with an optional remote:
  - `useIsInstanceAdmin()`: five pages hand-roll `me.instance_role !== "admin"` — `jiraimport/ui/src/types.ts:5` + `ImportPage.tsx:35`, `confluenceimport/ui/src/SettingsPage.tsx:12,30`, `ai/ui/src/settings/types.ts:109` + `AiSettingsPage.tsx:23`, `ldap/ui/src/DirectoryPage.tsx:21`, `leave/ui/src/LeaveSection.tsx:28`. The SDK's own `usePermissions` (`hooks.ts:42`) reads `global_role ?? instance_role`, the credential-aware value, so the two can disagree. This is a correctness fix as well as ~8 lines.
  - Props types for `automation.node.inspector` (ai hand-declares `InspectorProps` in `ai/ui/src/index.tsx:74-79`, and `inspectors.tsx:2` imports it back — a cycle; scripts casts inline) and for `issue.rail.top` (ai casts). Add `AutomationNodeInspectorProps` and `IssueRailProps` beside `EditorToolbarActionProps`.
  - `CheckField` (automations ×7, plus `mailintake/ui/src/shared.tsx:36` and `sso/ui/src/fields.tsx:6`).
  - `Segmented` (dashboards + host `report-state.tsx`) and `combineQueryWithFilters`/`splitQueryOrder` (dashboards `andFilter` + host `lib/slq.ts`).
  - `formatBytes` (jiraimport + monitoring + host `formatSize`).
  - `CopyValue` (pages `PublicPagesLinkRow` + host).
  - `ExtensionBlock` (pages + host ×2).
  - `ownTaskToggle` (pages ×2 + host ×2).
  - The paged step-back effect inside `usePagedDirectory` (pages + host ×3).
  - `OUTPUT_NAME_RE`: `automations/ui/src/automation-outputs.ts:17` is copied verbatim at `ai/ui/src/inspectors.tsx:74`. The ai remote may import only the SDK, so the one copy would live there.
  - Each is small; together they are the SDK's missing kit. Adding them grows the public surface, which is the trade to decide.
- **The signed-in user and preferences have two and three sources of truth.**
  - SDK `useCurrentUser` (`hooks.ts:20-27`) fetches `/auth/me` under `["radd-sdk","me"]`, while the host's `useCurrentUser` (`web/src/lib/hooks.ts:84-87`) reads `useAuthState()` (`web/src/lib/auth.ts:25`). Every page with a plugin surface that calls it (18 matches across plugin UIs) makes a second `/auth/me` request, and a profile change refreshes one cache and not the other.
  - `/auth/me/preferences` is read and PUT by `slots.tsx:279,333`, `ai/ui/src/queries.ts:41-45` and the host's `web/src/lib/topbar-prefs.ts`, under three keys.
  - Direction: the host provides the user and a preferences hook through the SDK, as it provides the API transport.
- **Build boilerplate across plugin UIs (outside this slice, ~600 lines repo-wide).**
  - 19 byte-identical `modules/*/ui/vite.config.mjs` files, 8 lines each (`md5sum` → one hash ×19).
  - 38 byte-identical `modules/*/ui/tsconfig.json` files, 17 lines each (one hash ×38).
  - Direction: a shared `tsconfig.plugin.json` to `extends`. `build-all.mjs` could call `raddRemote(dir)` itself and keep the file only as the "is a remote" marker that `plugin-packages.mjs:44` tests for.
- **Doc drift.**
  - `docs/plugin-ui.md:56,59` document the dead `sidebarNav`/`itemAction` slots.
  - `docs/modules.md:288` names `web/src/lib/queries/jira.ts` and a host `ProblemList`; neither exists.
  - CLAUDE.md's spec-124 narrative says "`lib/page-links.ts` is the only place the SPA assembles a page URL"; that file is gone, and the owner is `pages/ui/src/links.ts`.
  - `docs/specs/117-confluence-import.md:358-360` says the Jira components are "reused wholesale", which is impossible across remotes and not true in the tree.

### SDK

- **`slots.tsx` (856 lines) does four jobs.**
  - The `SlotId` catalog and the `SlotContribution`/`ContributionInfo` types (14-191) → `slot-ids.ts`.
  - The `SlotRegistry` with both toggle scopes and their server persistence (193-501) → `slot-registry.ts`.
  - The toggle hooks and ready-made toggle UI (560-751) → `contribution-toggles.tsx`, which the REDUNDANT item above shrinks to about 40 lines.
  - The render side — `useSlot`, `SlotErrorBoundary`, `ContributionFrame`, `Slot`, `useSlotMatch` (753-856) — stays in `slots.tsx`.
  - `index.ts` re-exports keep the public surface identical. About 0 net lines; four files of ≤300.
- **The no-host FALLBACK layer: about 200 lines that never execute in the shipped app**, because the host provides every one of these at boot.
  - The fallback bodies of `Button`, `TextField`, `Avatar` (+ `AVATAR_PX`, `fallbackHue`, `initials`) and `Modal` in `primitives.tsx`, about 90 lines.
  - Their CSS in `styles/components.css` (`.radd-btn*`, `.radd-input`, `.radd-modal*`), about 75 lines. `git grep -l 'radd-btn\|radd-input\|radd-modal'` → only `primitives.tsx`.
  - `api.ts:48-90`, the SDK's own fetch path, about 43 lines. It runs only when `provideApiTransport` was not called; the host calls it at `web/src/lib/api.ts:297`, and `audit-regressions.test.mjs:81` installs a transport too.
  - The comments justify these as "a remote's own test harness", but none exists: `examples/acme-notes` has no tests, and no proof renders the SDK without the host.
  - Decide whether the SDK must render standalone. If not, the fallbacks become `null`/"unavailable".
  - The `.radd-field/-select/-textarea/-chip/-card/-empty/-spinner` classes ARE live (Not bloat).
- **Kit placement is inconsistent.**
  - `DirectoryPager` (host `web/src/components/DirectoryPager.tsx`, 19 lines, depends only on the host `Button`) and `ListSearchInput` (host, depends only on lucide `Search`) are host components bridged back through `HostComponents` with SDK fallbacks (`host.tsx:70-82`).
  - Comparable leaf components (`Pager`, `Switch`, `IconButton`, `CollapsibleCard`, `TokenMultiSelect`, `ErrorText`) were moved INTO the SDK (RADD-1375).
  - Moving these two removes two bridges, two fallbacks and two `provideHostComponents` entries (about 15 lines), and follows CLAUDE.md's "kit from the SDK" rule.
- **Public exports with no consumer in the repo — FLAG, not delete, since external plugins may use them.**
  - `unregisterSlot` + `SlotRegistry.unregister` (`slots.tsx:396-405, 512-515`, 14 lines). The loader withdraws with `unregisterPlugin`, and `PluginContext` does not expose it.
  - `useItemQuery` (`hooks.ts:76-83`, named in `docs/plugin-ui.md:569,676`).
  - `useApiQueryClient` (`hooks.ts:94-97`).
  - `pageExtensions()` (`page-extensions.tsx:67`; the insert menu reads the server).
  - `LiveRole` (`live-documents.tsx:31`; only its type is used).
  - Index re-exports of values used only internally: `ConfirmDialog`, `OPTION_CONTROL_SLOT`, `changeLabel`, `humanize`, `formatChangeValue`.
  - Evidence: `git grep -nw <name>` → only the SDK and docs.
- Outside this area, noticed: `leave/ui/src/LeaveSection.tsx:16` defines its own inline-styled `ErrorText`, although the SDK exports one.

### automations

- **Files over ~300 lines, and where they split.**
  - `types.ts` (589): catalog types (55-174), graph and rule types (242-400), report and run types (402-474, 559-589), and intake validation (476-526 — the only part the host imports, through 7 files, so give it its own `./intake` export).
  - `ActionParams.tsx` (588): `TokenizableField` (28-124) to its own file; `SendEmailParams` leaves with the boundary fix above.
  - `GraphCanvas.tsx` (538): `GraphNode` (59-227) + `summarise` (254-315) → `GraphNode.tsx`, leaving about 300.
  - `GraphInspector.tsx` (508): the trigger section (282-386) → `TriggerFields.tsx`.
  - `RuleTestPanel.tsx` (425): `RunResultView`, `NodeRow` and `ActionPreviewRow` (233-425) → `RunResultView.tsx`. `RunsPanel.tsx:18` currently imports the shared renderer from the dry-run panel.
  - `GateFields.tsx` (409): split `FieldChangedFields`/`ChangeSide` from the simple gates.
- **Hand-rolled action buttons and a hand-rolled confirm, against the kit rule.**
  - `SettingsPage.tsx:199-217` is an inline Delete/× confirm, while `VersionsPanel.tsx:38,50-57` already uses `useConfirm` (about 15 lines).
  - Also `RuleEditor.tsx:133-140` (the back link) and `:207-222` (tabs), `GraphEditor.tsx:291-303` (the orientation toggle), and `CreateItemFields.tsx:221-232` (a "×" that should be an `IconButton`).
- **`ActionsBuilder.tsx` no longer builds action lists** (it holds `PickerData` plus action validity). A rename must also update `plugin-boundaries.test.mjs:192`, which reads the file by path.

### pages

- **Raw palette utilities against the frontend convention**: `text-red-400` at PageHistory.tsx:29, PageLinkedItems.tsx:76,146 and NewFromTemplate.tsx:94; `hover:text-red-400` at PageComments.tsx:122; `emerald-*` at PublicBadge.tsx:8. A mechanical token swap; the slice already uses `text-status-danger-ink` elsewhere.
- **`view/PageTree.tsx` (319 lines)** falls under 300 once the pure tree operations move to `view/page-tree.ts` (REDUNDANT #2).
- **The host reaches into the pages plugin's write path.** `web/src/components/shell/PinsBar.tsx:252-281` builds the create-page request itself (`PageApi.pages`, `PageCreate`, `pageByPathQuery`, `pageSpaceByIdentityQuery`, `Permission.pageWrite`). Pages should contribute "New page" (a slot, or at least `useCreatePage`). About 30 lines move.
- **Pages hardcodes the host's issue route** (`endpoints.ts:52 ISSUE_ROUTE`, used by ImportExtensions.tsx:185 and PageLinkedItems.tsx:91) while the SDK offers `ItemKeyLink`/`ItemPeek`.

### importers

- **The two sibling importer pages diverge in chrome and conventions.** Confluence uses:
  - `ul` lists instead of the SDK `Table`;
  - raw `<p>Loading…</p>` and `<p>Only instance admins…</p>` (`SnapshotsPanel.tsx:58`, `SettingsPage.tsx:57`) instead of `TableSkeleton`/`EmptyState`;
  - raw `<button>` actions (`RunsPanel.tsx:152`, `PlanEditor.tsx:129,175`);
  - wire literals (`"create"`, `"ignore"`, `"extension"`, `"done"` in `MappingRows.tsx:64-93`, `MappingTarget.tsx:19-46`, `SnapshotsPanel.tsx:106`) against rule 2.

  It also has no `PlansPanel`, so plans cannot be deleted from the UI. Direction: adopt Jira's conventions.
- **An SDK import kit, if wanted later:** about 150–250 net lines saved for about 250 lines of new public API, after aligning the backend shapes (`jiraimport/schemas.py:19-28` vs `confluenceimport/schemas.py:65-74`; `RollbackPreflight.edited_since` `list[str]` vs `int`). Not now.
- **`jiraimport/ui/src/UsersTable.tsx:37,99-112,206-220` loads the whole directory (`GET /users`, unpaged without `limit`, `auth/router.py:605-624`) into native selects**, one per row, and a live import has "300 unmatched people". The SDK's paged `DirectorySelect source="auth.people"` (used by Confluence, `MappingTarget.tsx:29`) shows only `name`. Direction: give `auth.people` choices an email line, then switch. This is a behaviour change.
- **UI gaps exposed by unread type fields** (worth filing):
  - `ConfluenceRun.report.rows` is never rendered.
  - `ConfluenceJiraLinkMapping.radd_project_key` has no editor.
  - Confluence user rows never show `display_name`/`email`.
  - `ComponentAction.FIELD` is never suggested or offered (`jiraimport/transform.py:77`, `plan/suggest.py:380`, `CatalogTables.tsx:150-151`).
- **Consistency, about 0 lines:**
  - `jiraimport/ui/src/api.ts` hand-types `({ signal }: { signal: AbortSignal })` 13 times; Confluence uses `queryOptions`.
  - `FieldRow.tsx:254-264 CommaOptions` edits a flat value set as comma text where the house rule is `TokenMultiSelect` (a UX change).

### ai

- **`ai/ui/src/inspectors.tsx` (170 lines) styles with inline `style={}` built from SDK `tokens`**, while every other ai file uses semantic classes (which work in remotes via `web/src/index.css:3` `@source`). The same style appears in 7 other remotes. Convert it when next touched; roughly line-neutral.

---

### F part — automations UI

- **Core UI carries two optional plugins' action forms.** About 80 lines would move out of core.
  - **Why:** RADD-1387 moved `action.send_email` to mailintake (`core=False`, `mailintake/__init__.py:29`) and `action.add_participant` to participants (`core=False`, `participants/__init__.py:54`) on the backend. The backend enum now says so (`automations/types.py:120-123`). The UI mirror did not follow: `types.ts:177-211 ActionType` still lists both and calls itself a "mirror of backend `ActionType`".
  - **Where core still carries them:**
    - `ActionParams.tsx:361-371`, `451-452` and `507-559` (`SendEmailParams`, 53 lines);
    - `ActionsBuilder.tsx:104-106` and `117-118`;
    - `types.ts:214-222` (`EmailRecipient`, a vocabulary the server moved to mailintake);
    - `automation-nodes.ts:205-233` (`EMAIL_ROLES`, and the `send_email` branch of `arityForcedReason`).
  - **Why it matters:** this breaks the plugin-ownership rule the AI and scripts nodes already follow (`automation.node.inspector`, RADD-1325).
  - **Latent trap:** `GraphInspector.tsx:111-113 hasCoreEditor` returns true for any `action.*` key. A future contributed `action.<x>` would therefore render no form (`ActionParams` `default: return null`) and never offer its inspector slot. `ActionsBuilder.tsx:119-120 default: return false` would mark it incomplete forever, and `RuleEditor.tsx:90-91` blocks Save.
  - **Direction:** mailintake and participants register `automation.node.inspector` for their keys; `hasCoreEditor` tests the built-in `ActionType` set instead of the prefix; unknown action types count as valid, and the server's 422 decides.
- **Files over about 300 lines, and where to split them:**
  - `types.ts` (589): split into catalog types (55-174), graph and rule types (242-400), report and run types (402-474, 559-589), and intake validation (476-526; the only part the host imports, through 7 files, so give it its own `./intake` export).
  - `ActionParams.tsx` (588): move `TokenizableField` (28-124) to its own file; `SendEmailParams` leaves per the item above.
  - `GraphCanvas.tsx` (538): move `GraphNode` (59-227) plus `summarise` (254-315) into `GraphNode.tsx`, leaving about 300.
  - `GraphInspector.tsx` (508): move the trigger section (282-386, about 105 lines) into `TriggerFields.tsx`.
  - `RuleTestPanel.tsx` (425): move `RunResultView`, `NodeRow` and `ActionPreviewRow` (233-425) into `RunResultView.tsx`. `RunsPanel.tsx:18` currently imports the shared renderer from the dry-run panel.
  - `GateFields.tsx` (409, about 395 after the deletes): split `FieldChangedFields`/`ChangeSide` from the simple gates.
- **The served catalog carries 3 fields no client reads:** `manual_trigger`, `schedule_trigger` and `schedule_kinds`.
  - Server side: `automations/schemas.py:763-766`, `router.py:106`. TypeScript side: `types.ts:157-160`.
  - They were superseded by `trigger_kinds` (RADD-1323) and by the UI's own sentinel constants.
  - Evidence: `git grep -n "manual_trigger\|schedule_trigger\b\|schedule_kinds" -- server/src web sdk` finds only the schema, the router and 4 proof fixtures that fill them in (`browser-automation-canvas.mjs:15`, `browser-plugin-availability.mjs:35`, `browser-query-contributions.mjs:13`, `browser-schedule-contributions.mjs:17`).
  - Direction: drop them server-side, in the TS type and in the fixtures together.
- **Hand-rolled action buttons and a hand-rolled delete confirm,** against the CLAUDE.md "use the kit" rule:
  - `SettingsPage.tsx:199-217` is an inline Delete/× confirm, while `VersionsPanel.tsx:38,50-57` already uses `useConfirm`.
  - `RuleEditor.tsx:133-140` (the back link) and `207-222` (tabs).
  - `GraphEditor.tsx:291-303` (the orientation toggle).
  - `CreateItemFields.tsx:221-232` (a "×" that should be an `IconButton`).
  - About 15 lines saved for the confirm alone.
- **`RuleCreate` and `RuleUpdate` types have drifted from what is sent.** `RuleEditor.tsx:95-106` sends `note` (and `adopt_execution` on create), which neither type declares.
  - `payload satisfies RuleUpdate` does not catch this, because `payload` is a variable, not a literal.
  - Direction: add `note?`, and move `adopt_execution?` to where the server accepts it.
- **`ActionsBuilder.tsx` no longer builds action lists.** It holds `PickerData` plus action validity.
  - A rename (for example to `pickers.ts` and `action-validity.ts`) must also update `web/scripts/plugin-boundaries.test.mjs:192`, which reads the file by path.
- **Out of scope, noted:** `web/scripts/plugin-boundaries.test.mjs:207` sets `const ast = owner === "automations" ? [] : …`, so the "imports only the SDK and schedule-contract" assertions pass without checking anything for automations.

### F part — pages UI

- **`view/IncludedPage.tsx:85-87` — the "you do not have access" branch never fires.**
  - **Why:** it tests `error.message.includes("403")`, but `ApiError.message` is the server's string `detail` when there is one (`web/packages/plugin-sdk/src/api.ts:13`). `ForbiddenError` always carries one (`server/src/radd/exceptions.py:34-37`, default "forbidden"). A restricted page answers 404 by design (`router.py:358-363`).
  - **Result:** a space-level denial reads "no such page".
  - **Direction:** `error instanceof ApiError && error.status === 403`, or drop the branch if "no such page" is the intended wording for both.
  - **Size:** 3 lines.
- **`view/ChangeUrlDialog.tsx:28-34` — user-facing copy that no longer matches behaviour.**
  - It says "links that used the old slug do not [keep working]". Since RADD-1233/1234, every old address resolves through `page_path_history`.
  - The `/pages/{spaceSlug}/` prefix it shows omits the parent path, so for a nested page the preview is not the page's URL.
  - **Direction:** reword the copy, and show `pageHref(spaceSlug, parentPath)`.
  - **Size:** ~5 lines.
- **`view/PublicBadge.tsx` — stale tooltip and raw palette.**
  - `title="Readable without login at /kb"` and "(spec 74)": spec 74's `/kb` was deleted by RADD-1147. `/kb` is now only a legacy redirect (`web/src/lib/constants/routes.ts:165-168`), and a public space is read at `/pages/<slug>`.
  - It uses raw `bg-emerald-500/15 text-emerald-300`.
  - **Direction:** use a semantic token, and a tooltip like "Readable without signing in".
  - **Size:** 3 lines.
- **Raw palette utilities against the frontend convention** (CLAUDE.md: semantic tokens only). The slice already uses `text-status-danger-ink` at PageComments.tsx:186 and ArchivedPagesPanel.tsx:260.
  - `text-red-400`: PageHistory.tsx:29, PageLinkedItems.tsx:76,146, NewFromTemplate.tsx:94
  - `hover:text-red-400`: PageComments.tsx:122
  - `emerald-*`: PublicBadge.tsx:8

  Direction: mechanical token swap. 6 sites.
- **`view/PageTree.tsx` (319 lines) is over the ~300 limit.** The seam is the pure tree operations (`comparePagesNaturally`, `buildTree`, `loadExpanded`, the filter's ancestor keep). They move to `view/page-tree.ts` with the other walks (REDUNDANT #2). This brings it to ~270.
- **The host reaches into the pages plugin's write path.**
  - `web/src/components/shell/PinsBar.tsx:252-281` builds the create-page request itself: `PageApi.pages`, `PageCreate`, `pageByPathQuery`, `pageSpaceByIdentityQuery` and `Permission.pageWrite`.
  - It also imports `Page`/`PageCreate` types and `PageApi` from `@radd-plugin-ui/pages`.
  - The plugin-ownership direction would have pages contribute the "New page" action (a slot, or at least a `useCreatePage` export: REDUNDANT #6).
  - **Size:** ~30 lines moving.
- **Pages hardcodes the host's issue route while the SDK offers `ItemKeyLink`.**
  - `endpoints.ts:52` defines `ISSUE_ROUTE = "/issues/$itemKey"`, used by ImportExtensions.tsx:185 and PageLinkedItems.tsx:91.
  - The SDK's `ItemKeyLink` (`host-surfaces.tsx:64`) is used by dashboards and approvals.
  - The ImportExtensions key cell is a straight swap. PageLinkedItems wraps key and title in one link, so it needs `ItemPeek` or stays as it is.
- **CLAUDE.md drift (outside this slice, one line).** The spec-124 narrative says "`lib/page-links.ts` is the only place the SPA assembles a page URL". That file no longer exists; the owner is this plugin's `links.ts` (RADD-1392).

### F part — importer UIs

- **The two sibling importer pages diverge in chrome and conventions, although spec 117 says the Jira components are "reused wholesale".**
  - `docs/specs/117-confluence-import.md:358-360` names `MappingSection`/`splitByUse` and `ProblemList` as reused wholesale. That is impossible across remotes, and in the tree Confluence uses `<details>` and its own `ProblemList`. It also has no `PlansPanel`, so its plans cannot be deleted from the UI.
  - Confluence differences from Jira:
    - `ul` lists instead of SDK `Table`;
    - raw `<p>Loading downloads…</p>` and `<p>Only instance admins…</p>` (`SnapshotsPanel.tsx:58`, `SettingsPage.tsx:57`) instead of `TableSkeleton`/`EmptyState`;
    - raw `<button>` actions (`RunsPanel.tsx:152` "Fix in…", `PlanEditor.tsx:129,175`) against the kit rule;
    - wire literals (`"create"`, `"ignore"`, `"extension"`, `"done"` in `MappingRows.tsx:64-93`, `MappingTarget.tsx:19-46`, `SnapshotsPanel.tsx:106`) where Jira uses const objects (rule 2).
  - Direction: pick Jira's conventions for the Confluence page; the effort is about the size of the REDUNDANT items above.
- **An SDK import kit, if wanted later.** Shared `ConnectionsPanel`/`ConnectionModal`/`ProblemList`/stage chip would net about 150–250 lines across the two packages, with about 250 lines of new public SDK API.
  - Precondition: align the backend shapes first. Status is `account/error/connection_name` (`jiraimport/schemas.py:19-28`) vs `user/detail` (`confluenceimport/schemas.py:65-74`); `RollbackPreflight.edited_since` is `list[str]` vs `int`.
  - Recommendation: not now (see Summary).
- **The instance-admin check is hand-rolled in five plugin UIs.**
  - The copies:
    - `jiraimport/ui/src/types.ts:5` `INSTANCE_ADMIN` + `ImportPage.tsx:35`;
    - `confluenceimport/ui/src/SettingsPage.tsx:12,30`;
    - `ai/ui/src/settings/types.ts:109`;
    - `ldap/ui/src/DirectoryPage.tsx:21`;
    - `leave/ui/src/LeaveSection.tsx:28`.
  - All five read `instance_role`. The SDK's own `usePermissions` (`plugin-sdk/src/hooks.ts:42`) reads `global_role ?? instance_role`, the credential-aware value, so the two can disagree.
  - Direction: export `useIsInstanceAdmin()` from the SDK, built on the same expression, and delete the five copies (about 8 lines, plus a correctness fix).
- **`jiraimport/ui/src/UsersTable.tsx:37,99-112,206-220` loads the whole admin directory (`GET /users`, unpaged when no `limit`) into native selects.**
  - `auth/router.py:605-624` shows the route is unpaged when no `limit` is passed.
  - There is one select for the bulk fallback and one per matched/fallback row, and a live import has "300 unmatched people".
  - The SDK's paged `DirectorySelect source="auth.people"` is what Confluence uses (`MappingTarget.tsx:29`). It shows only `name`, though, and RADD-769's reason for the local list is matching by address.
  - Direction: give `auth.people` choices a secondary line (email), then switch. This is a behaviour change, not a mechanical cleanup.
- **UI/backend gaps that the unread type fields expose (not bloat, but worth filing):**
  - `ConfluenceRun.report.rows` is never rendered, so a Confluence dry run shows counts only.
  - `ConfluenceJiraLinkMapping.radd_project_key` has no editor: `MappingTarget` returns null for `jira_links`.
  - Confluence user rows never show `display_name`/`email`.
  - The backend's `ComponentAction.FIELD` (`jiraimport/transform.py:77`, `plan/validate.py:230`) is never suggested (`plan/suggest.py:380`) and never offered (`CatalogTables.tsx:150-151`). It is reachable only over raw REST.
- **`jiraimport/ui/src/api.ts` hand-types `({ signal }: { signal: AbortSignal })` 13 times, plus a hand-written `refetchInterval` query type.** Confluence uses TanStack's `queryOptions`, which infers both. Adopting it is consistency, about 0 lines.
- **`jiraimport/ui/src/FieldRow.tsx:254-264`: `CommaOptions` edits a flat value set as comma-separated text.** The house rule (memory: prefer inline-token multi-select) is `TokenMultiSelect` from the SDK. It is a UX change, so it is a flag, not a delete.
- **Cross-cutting, outside this slice:**
  - `tsconfig.json` is byte-identical across 38 plugin UIs (`md5sum … | uniq -c` → 38 ×1 hash), 17 lines each; a shared `tsconfig.plugin.json` to `extends` would remove about 14 lines ×38.
  - `docs/modules.md:288` still names `web/src/lib/queries/jira.ts` and a host `ProblemList`; neither exists (`ls` → no such file). Row 289 supersedes it.
  - `automations/ui/src/RunsPanel.tsx:27` `RUN_STATUS_LABEL` is exported but used only in-file. That belongs to the automations fork.

### F part — ai + dashboards UIs

- Admin gating is hand-rolled across plugin UIs and has drifted from the SDK. `ai/ui/src/settings/AiSettingsPage.tsx:23` (with `settings/types.ts:108-109`) checks `me.instance_role !== "admin"`. `confluenceimport/SettingsPage.tsx:30`, `jiraimport/ImportPage.tsx:35`, `ldap/DirectoryPage.tsx:21` and `leave/LeaveSection.tsx:28` do the same. Meanwhile the SDK's `usePermissions` (`plugin-sdk/src/hooks.ts:42`) reads `global_role ?? instance_role`, "the server's credential-aware bypass" (RADD-1392). Direction: an SDK `useIsInstanceAdmin()`, with the five pages switched to it. ~5 files, −1 constant each.
- The SDK publishes no props type for two slots the ai plugin fills:
  - `automation.node.inspector`: `ai/ui/src/index.tsx:74-79` hand-declares `InspectorProps` (and `inspectors.tsx:2` imports it back from `./index`, a cycle), and `scripts/ui/src/index.tsx:19-22` casts inline.
  - `issue.rail.top`: `index.tsx:47` casts to `{ item: {id; title} }`.

  Every other slot ai uses has an SDK type (`EditorToolbarActionProps` etc., `plugin-sdk/src/editor-extensions.ts:121-154`). Direction: export `AutomationNodeInspectorProps` and `IssueRailTopProps` from the SDK (the parent's SDK area). ~8 lines here.
- `ai/ui/src/inspectors.tsx` (170 lines) styles with inline `style={}` objects built from the SDK `tokens`. Every other ai file uses the semantic Tailwind classes, and those work in remotes because `web/src/index.css:3` `@source`s every plugin's `ui/src`. The same inline-token style shows up in 7 other remotes (approvals, csat, leave, mailintake, milestones, participants, scripts). Direction: convert the ai file to classes when it is next touched; roughly line-neutral.
- `ai/ui/src/queries.ts:41-45` + `profile/EditorAiPreference.tsx` read and PUT `/auth/me/preferences` under their own key, as do the SDK (`slots.tsx:279,333`) and the host (`web/src/lib/topbar-prefs.ts`). That is three caches of one resource, and a PUT through one leaves the others stale. Direction: an SDK preferences hook. Small.
- 19 byte-identical `modules/*/ui/vite.config.mjs` (8 lines each) and 38 byte-identical `modules/*/ui/tsconfig.json` (17 lines each; `md5sum` gives one hash for 38). Direction: `tsconfig` `extends` a shared base; `build-all.mjs` could call `raddRemote(dir)` itself, with the file kept only as the "is a remote" marker `plugin-packages.mjs:44` tests for. Outside this slice; ~600 lines repo-wide.
- Outside the slice, not verified in a render: My Work may show each personal widget's heading twice. `WidgetGrid.tsx:59` draws `nameOf(widget)` ("Assigned to me" from `CARD_LABELS`), and the host's `web/src/routes/my-work.tsx:58` `WorkPreview` → `ListSection` draws its own `title` ("Assigned to me") inside the body. Worth one screenshot.

## FLAG — G — small plugin UIs + packaging

- **`gitlab/ui`, `github/ui`, `forgejo/ui` exist to ship static wording**
  - What: each package is `package.json` 14 + `tsconfig` 17 + `vite.config` 8 + `index.tsx` 21–24 lines ≈ 185 lines total. That buys 3 remote builds in `build-all` and 3 runtime `import()`s on Settings → Version control, only to ship a static `VcsHostConfig` object. The three `index.tsx` files differ only in the config strings and `order`. The ~15 real lines per connector are copy.
  - Direction: have the connector's Python manifest declare the wording (a `VcsHostSpec`, like nav labels and `SettingSpec` labels) and have the vcs core module list the loaded providers. The vcs bundled UI renders one tab each, and a disabled connector still loses its tab. This deletes 12 files.
  - Cost: `web/scripts/browser-vcs-settings.mjs:74-76` tests the remote-loading states ("Loading connectors…") and must be rewritten.
  - Est. −150 net.
- **Option sources: backend-declared instead of UI packages** (the bigger version of REDUNDANT #2)
  - What: forms, groups, itemtypes and releases are bundled UI packages (package.json 16 + tsconfig 17 + index 4 + options 15 ≈ 52 lines each) whose only content is transport for their own `/options` endpoint.
  - Direction: an `OptionSourceSpec(resource, noun, entities, hint_after, stacked)` on the manifest (policy stays in the plugin), exposed through capabilities, with one generic REST source registered by the host. That removes 4 packages and their `static.generated.ts` entries; workflow keeps its package for `transition-rule-contract`.
  - Tests: `browser-option-contributions.mjs:11` maps resources to owner plugins and needs adapting.
  - Est. −208 lines, −4 packages.
- **Two styling systems in plugin UIs**
  - What: 8 in-scope files style with inline `tokens` objects (1,158 lines, ~110 style lines): `approvals/ApprovalsCard.tsx` (25 token lines, 0 classNames), `csat/CsatChip.tsx`, `mailintake/ExternalRequesterChip.tsx`, `participants/ParticipantsSection.tsx` + `ParticipantChoices.tsx`, `leave/LeaveSection.tsx`, `milestones/MilestonesPage.tsx`, `scripts/ScriptInspector.tsx`. Every other package uses semantic Tailwind classes.
  - Why it matters: remotes can use classes, because `web/src/index.css:3` `@source`s `server/src/radd/modules/*/ui/src/**`. The inline-style `React.CSSProperties` objects are the verbose half. Converting would also retire a hand-rolled chip/button look that differs from the kit (e.g. participants' dashed "+ Add" button, removal ✕ buttons without `IconButton`).
  - Keep tokens in `examples/acme-notes`: it builds outside the host's `@source`.
  - Est. −80–120 lines.
- **`"radd-remote"` query keys are not dropped on disable**
  - Sites: `approvals/ApprovalsCard.tsx:79`, `csat/CsatChip.tsx:20`, `mailintake/ExternalRequesterChip.tsx:26`, `milestones/MilestonesPage.tsx:40`, and `participants/ParticipantsSection.tsx:30,40` plus `ParticipantChoices.tsx:26`.
  - Why it matters: `plugin-loader.ts:withdraw` removes only `["plugin-query", name]` and `[name]`, so these caches survive a disable. The convention (csat `survey.ts:64`, slas `report.ts:49`) is to key under the plugin name.
  - Direction: mechanical rename.
- **Files over 300 lines**
  - `approvals/ui/src/ApprovalsCard.tsx` (347): seam at lines 16-86, the inlined wire contract, status/verdict consts, paths and key. Move them to `types.ts`/`api.ts` and split the per-request row from the card.
  - `audit/ui/src/SettingsPage.tsx` (316): seam at `AuditRow`, lines 232-316 → `AuditRow.tsx`.
- **Core-plugin UI ownership split between host and package**
  - `backup`: the whole 636-line Backups page is host code calling `/backups` directly (`web/src/routes/settings/backups.tsx:202-590`). Only a 12-line preview wrapper around the SDK `ScheduleEditor` lives in `backup/ui`, behind a slot, a contract file and a host wrapper (`web/src/components/backup/ScheduleEditor.tsx`). Backup is `core=True`, so the "unavailable" fallback cannot render.
  - `reporting`: the chart kit is in the package, while the five report cards and the pages stay in `web/src/components/reports`.
  - Direction: pick one per module; for backup, move the page into the package or drop the package and slot.
- **Kit bypasses / inconsistent patterns** (CLAUDE.md "Use the kit")
  - `slas/settings/SlaSettingsPage.tsx:~140-160`: hand-rolled `<button>` Edit/Delete icons and an Enabled pill, and **Delete fires immediately with no confirm**. The rule "Delete asks first (RADD-1288)" is followed in milestones (`MilestonesPage.tsx:65`).
  - `mailintake/SignaturesPanel.tsx`: raw `<input>` and checkbox elements, text "Up/Down" buttons (RuleChainDialog uses arrow `IconButton`s), and `<p>Loading…</p>` instead of `Spinner`.
  - `approvals/AwaitingApproval.tsx:90`: `div role="button"`.
  - `fields/CustomFieldsForm.tsx:170-203`: `BooleanToggle` hand-rolls the SDK `Switch` (34 lines, including a raw `bg-white`).
  - `reporting/charts/report-state.tsx:56`: raw `text-red-400` (should be `ErrorText`) and its own `Loader2` spinner.
  - `monitoring/cards.tsx` `Card` (rounded-xl, shadow-lift, uppercase title) differs from the SDK `Card` that `MailHealthCard` uses in the same Monitoring page.
- **Shared shims nobody can use**
  - `react/jsx-dev-runtime`: no plugin source or built remote imports it (grep over 37 `ui/dist/*.js` found 0). The host's production bundle publishes React's production dev-runtime, whose `jsxDEV` is `void 0` (`node_modules/react/cjs/react-jsx-dev-runtime.production.js`), so the shim cannot serve any remote.
  - `react-dom/client`: 0 importers (a remote mounting its own root contradicts the slot model).
  - Direction: removing both touches the 4 lists that `plugin-boundaries.test.mjs` holds in sync: `shared-modules.mjs` `EAGER_MODULES`, `web/index.html:24,26`, `web/src/shared-runtime.ts:10,12,42,44`, and `plugin-sdk/vite.mjs` `SHARED`, plus 2 generated shims. ~−25 lines.
- **Phantom dependency**: `web/packages/plugin-sdk/vite.mjs:18` imports `rolldown/plugins`, which is declared nowhere. It resolves only as vite's transitive dependency (`vite/package.json` `"rolldown": "~1.1.5"`). Declare it in the SDK's peer/dev deps: an external plugin built against a different vite would break.
- **Non-`@radd` deps in plugin package.json are inconsistent**: `lucide-react` is declared by 3 packages (automations, collab, dashboards) and imported undeclared by 20. Nothing reads these declarations: installs happen in `web/` and plugin `node_modules` is a symlink. Either declare them consistently or state that only `@radd-plugin-ui/*` deps are checked (`plugin-boundaries.test.mjs:252`).
- **`examples/acme-notes/README.md:3`**: the "Current package/deployment workflow" line sits before the intro paragraph. The attachment table lists 7 of the 11 contribution rows `index.tsx` declares (missing `viewType`, `dashboardWidget`, `pluginManagerSection`, `profileSection`, which are described later in prose).

## FLAG — H — proof scripts

**Broken by drift.** Each of these fails today by static evidence; none is run by anything. Sorted by size:

- **`intake-validation-proof.mjs` (461 lines).**
  - The fixture (`graphFor`, lines 72-97 and 330-350) uses `type: "validation.fail"` and trigger `params.mode`. The server refuses both since RADD-1329 (`automations/service.py:472`).
  - It clicks `/^\s*new item\s*$/i` (line 220), but the button reads "New issue" since RADD-1287 (`PinsBar.tsx:296`).
  - It navigates to `/p/${key}/issues` (line 211). No such route exists; the path falls to `pluginPageRoute`'s catch-all.
  - The UI under test still exists ("Validate & create" and "Create anyway" in `NewItemModal.tsx:654-663`).
  - **Direction:** rewrite `graphFor` with `verdict.block` / `verdict.warn` nodes and no `mode`, click "New issue", and use `/p/${key}`. That is about 40 lines touched. `docs/specs/119` names this proof.
- **`notification-matrix-proof.mjs:234`.** It clicks `[role="option"]` in the subscription picker. Since RADD-1115 that picker is a dialog of `li > Button` (`SubscriptionTargetPicker.tsx:24`), so `clickAt` throws. The `!/Nothing left/` guard at 225 is vacuous: that copy is gone.
- **`ai-validate-node-proof.mjs:56`.** `EXPECTED_PORTS = ["pass","fail","unavailable"]`, but the server declares `(pass, fail, warn, unavailable)` (`ai/automation_node_validate.py:59`). Add `"warn"`; the RADD-1074 half is under DELETE.
- **`settings-cleanup-proof.mjs:101-102, 214-215`.** `[aria-label="Role to grant"]` and `input[placeholder*="teams and directory groups"]` were removed in RADD-1115/1121 (`git log -S'Role to grant'` gives `44feb561`). Two checks fail permanently. Point them at the current grant dialog.
- **`inline-comments-proof.mjs:138, 236`.** "and it is marked as orphaned" expects the "no longer match the page text" footnote. RADD-1276 (`32472573`) replaced it with the Detached group, and `page-detached-comments-proof.mjs:87` asserts the footnote is ABSENT. Drop item 4 (it is covered by `page-detached-comments-proof`) or assert the Detached group.
- **`project-rail-proof.mjs:37, 108-110`.** It expects an overflow row "N more with only your own items". RADD-937 (`a070d2b5`, the same day the proof was written) replaced it with a Sidebar toggle (`Sidebar.tsx:439`). The two overflow checks have never passed on main since.
- **`admin-affordances-proof.mjs:99, 102`.** `/item(s)? (hold|list) this option|No items use this option/` and `/move those items to/`: the copy has said "issues" since RADD-1287 (`FieldOptionsSection.tsx:175-181`). The `offersDestination` and `offersEmpty` fields are computed and never asserted.
- **`salvador-reports-proof.mjs:122`.** `session.click("button", (t) => /New item/.test(t))` throws since RADD-1287, so the RADD-1230 and RADD-1231 sections never run. Line 138 also names `[data-item-title]`, which never existed.
- **`editor-parity-proof.mjs:151-157`.** It finds the "New item" button by text, title or aria-label. None matches since RADD-1287, so the modal never opens and "the new-item modal mounts the same editor" fails.
- **`new-item-fields-proof.mjs:30-31`.** `/p/${key}/issues` (no route) and a `new item` click (throws since RADD-1287).
- **`storage-email-proof.mjs:87`.** It clicks "Add host", renamed "New host" in RADD-1287 (`storage/HostsPanel.tsx:109`). `docs/service-desk-email-images.md:56` tells people to run it.
- **`browser-second-review.mjs:96-98`.** The first step waits on `[data-integration-automations="Email"]` (removed in RADD-1370), so the unique checks after it never run: GitHub host Pause/Resume, the "Ingest webhooks" toggle, the host Test error, and a dry run of an unsaved graph. `research/review-2026-09-25/FIXES.md:87` calls it "permanent regression coverage", but it is in no runner. **Direction:** drop the Email step, use `automation-ui-fixture.py`, and add it to `test:browser` (or fold its checks into `browser-vcs-settings` and `browser-automation-editor`).
- **`page-print-proof.mjs:135`.** `[data-top-bar]` exists nowhere, and `TopBar.tsx` has no marker. `hasTopBar` really tests only the sidebar rail's `nav[aria-label='Primary']`.
- **`scripts-plugin-proof.mjs:102, 193`.** `!document.querySelector("[data-scripts-library]")` has been permanently true since RADD-1272 removed the attribute. It is a vacuous guard.

**Other flags:**

- **Screenshots written into the source tree, with no ignore rule (the task's item 6).**
  - 17 proofs call `session.screenshot(resolve("scripts", "<name>.png"))`, 29 calls in total: ai-settings-page, alertmanager-settings, approval-rule-editor, audit, board-collapse, comment-replies, email-automatic-messages, history-links, page-archive, page-paths, pager-size, project-delete, remus-reports, salvador-reports, secret-mask, sharing-wording, signin-settings-page.
  - `vcs-time-mirror-proof.mjs:35` uses `resolve(process.cwd(), "web/scripts")`.
  - That makes 32 paths. 24 PNGs are untracked in `git status` right now.
  - `resolve("scripts", …)` is **cwd-relative**: run from the repo root, it writes into the tracked `scripts/` release-tooling directory.
  - Neither `.gitignore` nor `web/.gitignore` has a PNG rule (`git check-ignore web/scripts/ai-settings-page-proof.png` exits 1).
  - About 40 other proofs already write to `$TMPDIR` or `/tmp`.
  - **Direction:** add `web/scripts/*.png` to `web/.gitignore` now, and move the 18 proofs to `$TMPDIR` through one lib helper.
- **`browser-issue-features.mjs` (175 lines) is maintained (last touched in RADD-1401), mock-only and not in `test:browser`.** Add it (and fix its header, see TRIM).
- **`plugin-boundaries.test.mjs` (611 lines).** Split it at the seam between:
  - the generic packaging invariants: lines 29-43, 238-262, 375-413, 471-488 (import boundaries, package exports, the generated static list, the SDK shim, shared singletons);
  - the per-feature ownership ratchets: 44-370, 414-570.

  That gives about 150 + 460 lines.
- **`automations-dataflow-proof.mjs` (793 lines).**
  - About 250 lines (147-400) are page-eval probe constants (`OPEN_RULE`, `SEARCH_NODES`, `ADD_NODE`, `SET_FIELD`, `PICK_OPTION`, `SAVE`, `SAVE_STATE`, …) re-typed in `ai-validate-node-proof` and `intake-validation-proof`.
  - Across the 16 automation proofs, 65 distinct lines appear in 3 or more files (457 occurrences).
  - **Direction:** a `lib/automation-editor.mjs` (sign-in, create rule, open editor, search and add from the panel, save, teardown) would take about 25 lines out of each file.
  - These counts overlap with the api/post item under REDUNDANT; they were not added twice.
- **The real-backend plugin-ownership proofs share about 21 lines of boilerplate each.** Measured: 438 lines across 21 files, all lines appearing in 8 or more of them. The shared lines are argument and credential parsing, `/login` then `session.login` then `check("signed in")`, `const checks = []`, the `report` adapter, `close()` and `process.exit`.
  - **Direction:** `lib/proof.mjs` `startProof({port, profile})` returning `{session, check, finish}`.
  - This overlaps with the waitFor, api and check items, so it is not added to the totals.
- **Aggregated reporting.** 9 automations proofs plus `plugin-contribution-proof` fold every assertion into one boolean (`report({"automations graph (spec 116)": ok})`) and print the JSON. A failure does not name the broken check, unlike `lib/cdp.mjs` `report(checks)` everywhere else.
- **Hand-picked CDP ports.** 27 ports are claimed by two or more scripts (for example 9451 ×4, 9459 ×4, 9357 ×3, 18787 ×2). `openBrowser` could pick a free port itself, which would retire the per-script constants and `RADD_PROOF_PORT_OFFSET`.
- **Doc drift.**
  - `CLAUDE.md` ("Verifying UI work") says `web/scripts/render-proof.mjs` "shows the zero-dep CDP pattern". That file is the pre-`lib` hand-rolled harness. The pattern to copy is `lib/cdp.mjs` `openBrowser`, so the pointer sends new proofs to the version missing six lessons.
  - `lib/mock-llm.mjs:4` names `ai-surface-proof` as its consumer.
- **`lib/cdp.mjs:157` `login(baseUrl, email, password)` ignores `baseUrl`.** About 100 callers pass it. It is harmless, but the signature misleads.
- **Undocumented tooling.** `docshot.mjs`, `docshot-smoke.mjs`, `publish-docs.mjs`, `verify-docs.mjs` (RADD-1001/1002) and `readme-shots.mjs` (RADD-1138) are referenced by no doc. `docs/publishing.md` covers only `scripts/publish_wiki.py`. Document them there or retire them.
- **`seed-extension-proof-page.py` (122 lines)** is the fixture creator `page-extensions-proof.mjs` needs (it makes the `render-proof` page with every extension), but nothing names it. Put it in `page-extensions-proof.mjs`'s Usage line.
- **Overlapping pairs, all complementary rather than superseded:**
  - `mail-settings-proof` and `email-settings-page-proof` share about 5 checks (page renders Incoming/Outgoing, the Server overview row links, the source dialog opens with a default project). The first alone checks secret masking and the Gmail/IMAP presets; the second alone checks remote ownership and rename/delete. Merging would save about 60 lines.
  - `extension-insert-proof` and `extension-menu-proof` both open the insert menu. insert alone checks hit-testing (RADD-742) and the saved fence.
  - `automations-canvas-edit-proof` and `automations-editor-proof` both add nodes from the panel. canvas-edit alone checks the unwired warning and the inspector opening. Merge candidate.

## FLAG — I — prose: docs, specs, PLAN/BUILD-LOG/CLAUDE.md, research

- **`docs/modules.md` is no longer a map (684 KB).**
  - **Why it matters:** CLAUDE.md rule 3 makes this file the navigation entry point ("a new contributor … must be able to navigate from that file alone"). At 684 KB it cannot be read, and 241 commits of per-issue appends have left it contradicting itself (`:213` vs `:254`; `:889` vs `plugin-platform.md:1090`; `:336` vs CLAUDE.md rule 1).
  - **The spine paragraph is stale.** `:336` says *"two tables are the de-facto shared spine"* (User, Project). Rule 1 / RADD-885 names six modules and a test-enforced allowlist.
  - **Direction:**
    1. Generate the structural columns (depends_on, emitted event types, permissions, nav, contributed specs) from the `RaddPlugin` manifests, the way the SDK surface is derived by `web/scripts/sdk-exports.mjs`. Every one of those facts is already declared, e.g. `automations/__init__.py` lists `depends_on`, `event_types`, `permissions`, `automation_nodes`. `research/plugin-isolation/README.md:116ff` hand-maintains a second copy (core/bundled/depends_on).
    2. Keep one hand-written sentence of purpose/seam per module.
    3. Cap row length in a test, the same way the 300-line rule caps files.
    4. Replace `:336` with "See CLAUDE.md rule 1 (spine: auth, projects, items, workflow, teams, fields; enforced by `tests/test_module_contracts.py`)."
  - **Est.:** 684 → ≈70 KB.

- **`CLAUDE.md`: rules vs narrative. Owner's decision, not a DELETE.**
  - **RULES = 22.9 KB (31%):**
    - the rules sections `:37-271` (23.7 KB) minus ≈1.1 KB of history inside them;
    - plus the two live proof traps (`:28-31`).
  - **NARRATIVE = 51.2 KB (69%):**
    - `:33` wave narrative, 44,975 B;
    - `:35` "Where the build is", 2,600 B;
    - `:5-19` latest-wave summary, 1,803 B;
    - `:21-26` bugs found, 405 B;
    - `:3` upgrade note, 306 B;
    - ≈1.1 KB of history inside the rules.
  - **A slimmed CLAUDE.md keeps:**
    - a 4-line orientation (TRIM text above);
    - Development rules;
    - Tracking work (shape, loop, descriptions, time, attribution, MCP first);
    - Frontend conventions;
    - SLQ;
    - Verifying UI work (plus the two traps);
    - Running;
    - Releasing & deploying;
    - Repo layout.
    - That is ≈200 lines, ≈23 KB.
  - **The narrative goes to** `BUILD-LOG.md`, as newest-first entries, one per wave, each opening with its epic key and release tag.
  - **What no copy holds today:** the first ≈17 KB of `:33` (plugin-ownership back to spec 115). Those waves are otherwise only in their specs, `research/plugin-isolation` and the tracker. Move them, don't delete them.

- **Which narrative is the record (PLAN §8/§11 vs BUILD-LOG vs the CLAUDE.md preamble).**
  - **Proposal:** the record is the tracker (epics and issues, per CLAUDE.md rule 6 and PLAN.md:263-266 *"the roadmap lives in the tracker … this document stops being a second source of truth that drifts"*), plus `docs/specs/`, plus the git tags and release notes.
  - **One** narrative file indexes it: `BUILD-LOG.md`. It is already titled a log, already closed-and-historical in tone, and has no rules in it. Merge into it:
    1. `PLAN.md:297-1163` (§11 + Addenda 10–15, minus the stale ops notes);
    2. the CLAUDE.md preamble.
  - `PLAN.md` keeps §1–§7 and §9–§10 (mission, decisions, design, non-goals, risks, naming; ≈26 KB). §8 becomes a 3-line pointer to README's feature tour and the tracker roadmap.
  - **Rejected option:** keeping CLAUDE.md as the narrative. It is loaded into every agent session, so every byte of history is paid per session. It is also the only place the three copies disagree from.

- **Specs that need a "superseded by" line.** Never delete a spec. Specs 31, 50, 62, 69 and 74 already carry such a line; follow their form, for example:
  ```
  > **Superseded in part by <spec/issue> (<date>):** <one sentence on what changed>.
  ```

  | Spec | Superseded (in part) by | Evidence |
  |---|---|---|
  | 07 field grants | spec 92 | `field_permissions` → `access_grants`, migration `6fc5f7c71481_spec_92_generic_access_grants_migrate_` |
  | 15 automations | spec 116 + RADD-1265 | `automation_rules` columns gone: `d116graphs_automations_become_graphs.py`; `d1265autolegacy` |
  | 20 frontend automations/forms | spec 116 + RADD-1365 | `RuleEditor`/`ActionsBuilder`/`ACTION_TYPE_LABELS` have 0 hits; UI lives in `automations/ui` |
  | 29 attachments + editor | spec 102 (storage), RADD-745/754 (editor) | `git grep MarkdownEditor -- server/src web/src web/packages` = 0 |
  | 33 S3 storage | spec 102 | `attachments/hosts.py:340-352` "env seeding"; hosts are `storage_hosts` rows |
  | 36 rbac extensions (builtin-field rules) | spec 92 | migration `3d1e2f0f3823_spec_92_migrate_builtin_field_rules_to_`; `/field-rules` has 0 route hits |
  | 40 SSO OIDC | spec 110 (+ spec 86) | `config.py:248` "SEED-ONLY since spec 110"; `RADD_OIDC_DEFAULT_WORKSPACE_SLUG` gone |
  | 43 wiki | RADD-701, spec 122, spec 124-page-addresses, RADD-1392 | all 13 `/doc-pages`/`/doc-spaces` routes and `/docs/$spaceId/$pageId` are gone (`ad25bd34`) |
  | 46 AI | spec 101 | `config.py:337` "SEED-ONLY … creates one provider row" |
  | 47 connectors | spec 111 (Forgejo), RADD-958 (mail), RADD-1317 (Alertmanager), RADD-1319 (Google Chat) | no `googlechat` module (`ab12e117`); `mailintake/seeding.py:56,71,85` env is seed-only |
  | 57 view ownership/sharing | spec 92 | migration `925809931622_spec_92_migrate_view_shares_to_access_` |
  | 58 automation event conditions | RADD-1265 | condition tree deleted (`0dd82c92`); `ConditionsBuilder`/`EVENT_GATE_TYPES` have 0 hits |
  | 64 queue views | RADD-1201, RADD-1396 | `slas/types.py:33` `QUEUE_ROWS_PATH = "/sla-queue-items"`; `DEFAULT_QUEUE_SLOTS`/`QueueRowMeta` have 0 hits |
  | 90 Jira import wizard | spec 100 | spec 100 line 3: "Replaces the spec-90 wizard" |
  | 106 form assist (public path) | RADD-828, RADD-1147 | `search_public`, `test_public_kb.py`, `DeflectDocsSection` have 0 hits |
  | 112 release pipeline | RADD-1285 | `release_waiting/shipped_state` settings deleted, replaced by `workflow_transitions.on_release` (migration `d1285releaseflow`; `config.py:438`) |
  | 01/06/22/75/84 (workspace vocabulary) | spec 86 | no `workspaces` table or module; `workspace_id` survives in one comment |

  **Stale status lines:**
  - Specs 93 and 94 say *"Status: in progress"*. Both are merged; CLAUDE.md says so, and spec 94 was revised by RADD-1373.
  - Spec 115 says *"Status: audit + proposal. No code changed."* It was built (RADD-821…, shipped v0.18.0).

- **Spec number collisions.**
  - Two specs are numbered 124: `124-external-plugin-workflow.md` and `124-page-addresses.md`.
  - Two are numbered 125: `125-managed-plugin-packages.md` and `125-vcs-time-mirror.md`.
  - "spec 124" already means different things in different places. `pages/ui/src/links.ts:2` means page addresses. `plugin-platform.md:3`, `modules.md:139` and `plugin-development.md` mean the external plugin workflow.
  - **Direction:** renumber the plugin pair to 126/127 and update 5 links: `deploy.md:488`, `plugin-development.md:26`, `plugin-platform.md:3`, `modules.md:137`, `modules.md:139`.
  - Also noted: specs 41, 53, 54, 91 and 92 are cited everywhere but have no file. Spec 54 (the WYSIWYG editor) and spec 92 (the access framework) are load-bearing.

- **`docs/deploy.md:416-421` and `:433-445` present seed-only variables as the live configuration.**
  - `RADD_MAIL_IMAP_*`: *"unset host = intake is off entirely"*. False since RADD-958/970: `mailintake/seeding.py:56` seeds a `mail_sources` row; `dispatcher.py:5-12` "Neither loop is gated on the environment".
  - `RADD_SMTP_*`: `seeding.py:85`.
  - `RADD_EMAIL_INGEST_SECRET`: `seeding.py:71`; `router.py:73` falls back to the source row's secret.
  - `RADD_ATTACHMENT_STORAGE`/`RADD_S3_*`: `hosts.py:340` "env seeding".
  - `RADD_OIDC_*`: `config.py:248`.
  - **Direction:** add a "seed-only: configure in Settings → … after first start" column, following `config.py`'s own comments.

- **`research/` classification** (inbound references = `git grep` outside `research/`):

  | Path | Size | Inbound references | Class | Proposal |
  |---|---|---|---|---|
  | `plugin-isolation/README.md` | 827 lines, 72 KB | CLAUDE.md, modules.md, plugin-platform.md, `scripts/plugin_inventory.py:22-24` (LEDGER), `.gitignore:32` | live record | keep; point the other docs at it instead of restating it. Trim its 7 `/tmp/radd-…` evidence paths (ephemeral). |
  | `architecture.md` | 46 | `search/fusion.py:7` (code cites it), PLAN.md, modules.md | decision record | keep; its "Research date:" is blank |
  | `auth.md`, `landscape.md` | 83, 39 | PLAN.md §3/§5.7 | decision record | keep (same blank date) |
  | `audit-2026-08/` | 10 files, 1,594 lines | modules.md; migration `d895compat` docstring | decision record (self-declared historical) | keep |
  | `audit-2026-09-09/` | 35 files, 1,594 lines | modules.md (10 subdir links) | decision record + an OPEN ledger (`OUTSTANDING.md` rows D1–D5 "Open", RADD-1112) | keep; move the open rows to tracker issues; this dir receives `modules.md:468-733` |
  | `scale-audit-2026-09-18/` | 24 files, 17,303 lines | none | decision record (2 md) + raw evidence (22 files) | keep the md; delete the evidence (DELETE) |
  | `review-2026-09-25/` | 5 files, 778 lines | none | decision record (README, FIXES) + superseded probes | keep the md; delete the probes (DELETE) |
  | `issues-2026-09-25/` | 4 files, 91 lines | none | one-off per-issue notes | delete (DELETE) |
  | `page-comments-2026-09-18.md` | 36 | none | one-off per-issue note | delete (DELETE) |

- **The three review docs, and whether they are still true.**
  - `module-boundary-review.md`: 5 of 7 findings are fixed (DELETE entry has the evidence). #4 and #5 and the loader `module` fallback are still true.
  - `large-view-review.md`: the recommendation shipped, but the doc says it didn't.
  - `roadmap-ideas.md`: 3 small items remain, already on the tracker.
  - None of the three describes current design, so all three leave `docs/`.

- **Current-feature docs have two homes.**
  - `resolvable-threads.md`, `planning-pagination.md`, `grouped-queue-pagination.md` and `service-desk-email-images.md` are user/operator guides, and they are current (every route they name exists: `comments/router.py:150,157`, `items/router.py:64`, `slas/types.py:33`).
  - But `docs/publishing.md:66-75` says the user guide is written on project.radd-hq.com ("Radd Documentation") and mirrored to the GitHub wiki.
  - **Direction:** decide whether feature guides live in the wiki or in `docs/guides/`, and move them there. Mixed with design docs and dated reviews in `docs/`, they are hard to tell apart.

- **`docs/media/{board-light,issue-dark,reports-dark}.png` (390 KB) are not referenced by README.md.** `web/scripts/readme-shots.mjs:112-116,160-164,206-209` regenerates them on every run. Direction: use them (theme pair) or stop shooting them.

- **Per-doc stale-reference census.** "Checked" = backticked references; "stale" = verified present-tense claims that are false today.

  | Doc | Checked | Stale | Notes |
  |---|---:|---:|---|
  | `docs/modules.md` | 7,663 | ≥49 (+117 names of deleted things in history sentences) | TRIM / FLAG |
  | `CLAUDE.md` | 589 | 6, all in `:33` narrative | rules sections: 0 |
  | `docs/plugin-platform.md` | 407 | 5 | `plugin_migrations`, `system_access`, `radd._internal`, `/metrics` (unbuilt design), `module.py` (`:178`), plus the `OptionResource` claim |
  | `docs/plugin-ui.md` | 428 | 3 | GraphInspector path, PeopleDirectorySelect, "backend enum" |
  | `PLAN.md` | 486 | 29 | expected in history, e.g. `sync_workspace_membership`, `routes/planning.tsx`, `useSlqProbe`, `research/jira-usage.md` |
  | `BUILD-LOG.md` | 484 | 38 | closed history; expected |
  | `docs/module-boundary-review.md` | 44 | 4 | all fixed findings |
  | `docs/roadmap-ideas.md` | 36 | 1 + prose | `radd/module.py` |
  | `docs/deploy.md` | 137 | 0 names | env drift above |
  | `docs/deploy-k3s.md` | 32 | 0 | names live in the private deployment repo |
  | `docs/plugin-development.md` | 33 | 0 | |
  | `docs/contributing.md` | 18 | 0 | |
  | `README.md` | 8 | 0 | |
  | `sdk/README.md` | 32 | 0 | |
  | `examples/acme-notes/README.md` | 34 | 0 | |
  | `server/scripts/sample_data/README.md` | 9 | 0 | |
  | the other `docs/*.md` | — | 0 | apart from `docs/codebase-scan/03-deprecated.md` naming the removed `_fold_legacy_scope` (a historical finding) |
  | specs | — | — | see the supersession table; the highest stale ratios are 43 (44%), 74 (34%), 21 (24%), 86 (23%, deliberately — it names what it deleted) |

---

## FLAG — T — server tests, scripts, migrations

- **Giant files that should split at their existing section headers:**
  - `test_intake_validation.py` (1,516 lines): pure rules (`:137-474`, parsing/index/resolution) | enforcement (`:248-407` refusals, `:743-1083` savepoint flow plus other callers) | automation (`:474-743` walk/findings, `:1154-1376` builder plus contributed-node seam) | HTTP (`:1083-1154` form surfaces, `:1376-1516` endpoints).
  - `test_notify_mailer.py` (1,317): planning (`:344-875`, immediate / channel matrix / hand-off / non-mailbox accounts) | delivery (`:875-1317`, unsubscribe / backoff / transport / independence).
  - `test_automation_dataflow.py` (1,258): the bag and the walk (`:78-409`) | API refusals and token resolution (`:409-851`) | `ai.generate` (`:851-1055`) | refusal semantics (`:1055-`).
  - `test_mail_threading.py` (1,165): pure parsing (`:117-150`, `:924-1028`) | store threading and attribution (`:150-416`) | sender auth and contacts (`:416-750`) | retention/attachments/batching (`:1028-`).
  - `test_mail_config.py` (1,151): wiring/registry/poller/seeding (`:104-534`) | kind presets (`:534-790`) | sender identity (`:790-1151`).
  - `test_jira_pipeline.py` (970): plan/dry-run/import (`:235-451`) | relink/rollback (`:451-582`) | mapping edge cases (`:582-`).
  - `test_mail_render.py` (940): recipients/content (`:118-503`) | digest (`:503-644`) | transport/thread (`:644-`).
  - Size: 7 files, about 8,300 lines to redistribute, no net change.

- **`server/scripts/perfseed.py` no longer matches the schema.** `:585-591` inserts into `project_members` unconditionally inside `main()`, and `:923` VACUUMs it, but migration `d929grants_one_grant_model.py:86` dropped that table (RADD-929). On a head database the seeder therefore fails partway. The memory note calls it the live way to rebuild the perf dataset.
  - Direction: replace with `GlobalRoleGrant(project_id=…, role_id=member)` rows, or drop the block. Also run the 6 B007/F841 findings.
  - Size: about 10 lines to fix.

- **One-off data-repair scripts that have already done their job** (by the no-backcompat-until-V1 rule these are deletion candidates; the owner decides):
  - `scripts/backfill_cycle_history.py` (106 lines): "RUN on live", per `PLAN.md:622`.
  - `scripts/fix_jira_markup.py` (81): a back-fill for rows imported before the importer converted markup.
  - `scripts/reconcile_ad_users.py` (222): the "one-off cleanup" of spec 88 (`PLAN.md:935`).
  - All three are referenced only from PLAN/docs/spec prose and the migration comment at `c536f26534fb:33`. Size: about 409 lines plus about 6 doc lines.

- **`server/scripts/import_ad_users.py` (110 lines)** does the job of the in-app AD import (`ldap/router.py:174` → `userimport.plan_user_import`, `:243` → `apply_resolution`) without spec 88's duplicate resolution. `config.py:289` and `docs/modules.md:203` still describe it as the bulk path. Direction: retire it in favour of Settings → Directory, or document why the CLI stays.

- **`server/scripts/scripts_airgap_probe.py` (165 lines)** is referenced nowhere (`git grep scripts_airgap_probe` returns nothing), which breaks CLAUDE.md rule 3's "document the connections". Its docstring does carry the full recipe. Direction: add one line to `docs/modules.md` (scripts row), or move it next to the other proofs.

- **21 per-route bounds blocks.** 21 test files repeat the same "`limit` 201/0, `offset` -1, `q` × 201 → 422" loop, for example `test_cycle_directory.py:118`, `test_field_directory.py:188`, `test_wiki_directory.py:139` and `test_space_access_directory.py:143`. The bounds are declared per route in src (62 `Query(..le=)` limit params), so each block tests one declaration. Direction: one app-wide ratchet over the assembled routes, like `test_route_shadowing.py`, asserting every paged `limit` has `le` and every `q` has `max_length`. That saves about 60 lines and covers routes nobody wrote a block for.

- **The dense "directory" test style, and CI does not lint tests.** 14 files carry 229 E701/E702 semicolon one-liners: `test_team_stewardship` 38, `test_team_group_directory` 34, `test_space_access_directory` 31, `test_team_directory` 25, then the other `*_directory` / `*_options` files. 257 of 319 test files would be reformatted by `ruff format`. `.github/workflows/checks.yaml:53` runs `ruff check src` only, which is why the 20 findings above accumulated.
  - Direction: `ruff check src tests scripts` in CI. Then `test_code_hygiene.py:136-165` (`test_no_undefined_names`, which shells out to ruff F821 over src plus tests) becomes redundant, about 30 lines.

- **`test_capabilities.py:24-65` asserts tautologies.** `test_capability_checks_match_the_old_inline_logic` and `test_storage_ai_sso_and_forgejo_capabilities_reflect_their_db_snapshots` recompute the exact boolean each `CapabilitySpec.check()` computes (`bool(settings.ldap_url and settings.ldap_user_domain)` and so on). That was a parity oracle for the spec-93 chokepoint-2 migration, which is finished. Rule 4 suggests keeping only the registered-set and row-driven tests (`:16`, `:68`, `:87`). About 45 lines.

- **Tombstone assertions** (they only guard against reintroducing something already deleted; cheap, but not rule-4 value):
  - `test_builtin_role_sync.py:71` (`test_staff_is_gone`);
  - `test_scope_ladder.py:116-120` (`"instance"` not in the enum, `ALL_PERMISSIONS` not an attribute);
  - `test_capabilities.py:33,36` (`"smtp"` / `"mfa"` not in the map);
  - `test_requesters.py:104,107` (`/public/forms`, `/public/pages` absent; keep the `/public/csat` assertion at `:108`);
  - `test_public_pages.py:159` (`/public/pages/spaces` answers 404).
  - About 20 lines; the owner decides.

- **Tests grouped by review rather than by feature:** `test_review_interactions.py` (392 lines, 18 tests) and `test_second_review_interactions.py` (692 lines, 18 tests, importing the first file's `world`). Each case belongs beside its feature's tests (receivers, watchers, CI, scripts, act_as, VCS hosts). Filed that way, a future reader of `test_vcs_*` never sees them. Moving them is roughly neutral in size.

- **44 per-file `world` fixtures (1,205 lines)** and **61 in-body engine constructions in 44 files** (for example `test_team_directory.py:18-44`, where each test body builds its own engine, sessionmaker, app and client). Many shrink by half once `db`, the factories and `client_for` exist.
  - Module-scoped worlds (`test_intake_validation.py:1387`, `test_portal_requester.py:29`, `test_scoped_member.py:61`, `test_user_directory.py:30`, `test_view_as.py:28`) cannot use a function-scoped `db` and need a module-scoped variant.

- **The migration template generates unused imports.** 14 F401 findings in 9 migrations (merge heads and `2c9bd41c6a05`, `79554b33d374`, `d116graphs`, `e53d08a57e29`) come from `script.py.mako` always emitting `import sqlalchemy as sa` and `from alembic import op`. Leave the migrations alone (they are history). Optionally make the template emit them only when used. Size: none.

## Decisions for the owner — J — repo hygiene

1. **Research run evidence: one policy, not three.**
   - Today `research/audit-2026-09-09/` keeps evidence local (nested `.gitignore`: "the markdown carries the findings; the run evidence stays local … ~15 MB"). But its 31 tracked READMEs carry **352 links to those ignored files** (plus 7 to files missing even locally), all dead on a clone.
   - `research/scale-audit-2026-09-18/` commits its evidence: 17 JSON files, 914,305 B, with no emails, hosts or PIDs (grep counts 0), plus 5 scripts (25,811 B). Its README links them as "Sources" (lines 31, 64–65, 89, 118–120) and gives run commands (lines 475–480).
   - `research/review-2026-09-25/` commits probes (covered under Untrack).
   - Options:
     - **(A) Recommended:** generalise the audit-2026-09-09 rule to the root (`research/**/*.png`, `research/**/*.txt`, `research/**/*.json`, plus one-off `*.py`/`*.mjs` by convention). Untrack the scale-audit JSON, keeping its 5 harness scripts because the README documents how to rerun them. Turn evidence links into plain text ("evidence kept locally").
     - (B) Commit evidence everywhere. That would add about 13 MB for 09-09 alone, much of it screenshots.
     - (C) Leave the mix as it is.
2. **`docs/campaigns/` and `docs/tutorials/`:** where the 2.7 GB of generated media should live. Recommended: outside the repo, with the ignore rules above as a backstop. The pure-docs output (transcripts, feature reference) goes to the Radd wiki if wanted.
3. **`.mcp.json`:** ignored (`.gitignore:30`, "maintainer-personal"), but CLAUDE.md §"MCP first" tells every reader that "`.mcp.json` registers it once as `radd`", so a cloner reads about a file they do not have. The file holds no secret: it has the public instance URL and `Bearer ${VAR}` env expansion. Options:
   - Commit it (or `.mcp.json.example`) for contributors who hold an account on project.radd-hq.com.
   - Keep it ignored and have CLAUDE.md say it is local.
   - Recommended: keep it ignored, because the operational half already lives in the local `track` skill.
4. **Denylist hits already public:** the #3, #6 and #7 hits in `CLAUDE.md`, `docs/specs/125-vcs-time-mirror.md` (which names an internal GitLab host), `docs/modules.md`, `gitlab/timelogs.py`, `test_gitlab_timelogs.py` and `vcs-time-mirror-proof.mjs` are on `origin/main`.
   - Scrubbing the working tree is a text edit.
   - The unpushed #7 hit in `research/plugin-isolation/README.md:177` and the 12 machine paths in `research/review-2026-09-25/README.md` can be fixed before they ever reach GitHub.
   - Consider running the generic half of `publish-gate.sh` in `checks.yaml`. The machine-path check needs no denylist, and today nothing enforces the gate automatically.
5. **`docs/codebase-scan/` (6 files, 30,143 B):** a 2026-07 AI scan ("Historical snapshot … findings may already be fixed") filed under `docs/` while every later audit lives in `research/`. Nothing links to it (`git grep codebase-scan` finds nothing). Recommend moving it to `research/codebase-scan-2026-07/`.
   - The same question applies, with lower confidence, to the one-off review and fix notes in `docs/` that nothing references: `module-boundary-review.md`, `pilot-readiness-fixes.md`, `importer-attribution-fixes.md` (0 inbound references each), `large-view-review.md` and `performance-safety-audit.md` (1 each).
6. **`.claude/worktrees/`:** 22 registered agent worktrees (`git worktree list` → 23 including main), 12 GB, and 21 local `worktree-agent-*` branches. None are pushed; `git branch -r | grep -c worktree` → 0. They are ignored, so this is not a clone problem, but they make every `find`/context walk scan 12 GB. Pruning them is the owner's call.
7. **`.obsidian/` rule:** a per-machine vault. Keep it, or move it to `.git/info/exclude`. Either is fine.
