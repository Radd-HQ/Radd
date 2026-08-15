# Dead-code audit — Radd backend (`server/`), 2026-08-05

All paths relative to ``. Confidence: **CERTAIN** = zero references anywhere in the repo (server, web, sdk, scripts, docs, examples); **LIKELY** = only self/test/demo references; **SUSPECT** = a dynamic-dispatch or documented-external path is plausible.

**Method note (affects trust):** findings were produced by parallel sweeps plus direct verification. Two interim sub-audits produced fabricated findings (routes/models that do not exist in the tree); those were discarded wholesale and every finding below was either produced or re-verified by direct grep/AST/ruff against the working tree. One verification trap discovered on the way: `web/packages/plugin-sdk/src/slots.tsx` contains non-UTF8 bytes, so **plain grep treats it as binary and silently misses matches** — any future "the SPA never calls this" claim must grep with `-a` (this is exactly how `/plugins/*/contribution-settings` was nearly mis-flagged as dead; it is alive, called from plugin-sdk `slots.tsx:242,268`).

> **Editorial correction (verified after this report was produced):** the "verified alive" list in §2 includes `/health` — that is wrong. No `/health` route exists in `server/src/radd` (only `/hosts/{host_id}/health` in the attachments admin router). This matches the misleading-docs report (`04-misleading-docs-comments.md`, CLAUDE.md claim #3).

## Executive summary

| Category | Findings | Est. deletable lines |
|---|---|---|
| 1. Unused public functions/classes (service layer + kernel) | 37 | ~465 |
| 2. Unused endpoints | 12 CERTAIN routes + 4 LIKELY + 2 decide-clusters | ~300-350 |
| 3. Orphaned modules | 0 (milestones = documented installable north-star) | 0 |
| 4. Unused models/columns | 2 columns (+1 checked-alive) | ~15 + 2 drop migrations |
| 5. Unused config / env docs | 1 Settings field + 3 stale doc references | ~5 |
| 6. Unused Pydantic schemas | 13 classes + 1 enum | ~135 (~110 net of overlap) |
| 7. Unreachable code / phantom event types / unused imports | 1 `if False` + 3 event clusters + 39 import lines + 1 dead statement | ~60 |
| 8. Refactor leftovers | 6 code + 5 documentation | (counted above) |
| 9. Unused deps in pyproject | 0 | 0 |

**Total: ~1,000-1,100 deletable backend lines, ~80 deletable SPA lines (side findings), 2-3 drop-column migrations.** The codebase is notably clean at the function level (e.g. 684/687 functions in items/auth/views/events/fields/workflow have live callers); the real mass is in never-wired seams (kernel task/consumer plumbing, RADD-828 leftovers, the page-templates API family) rather than rotting feature code.

Three findings are more than hygiene:

- **`access.sweep_expired_grants` never runs** — registered as the only `TaskSpec` in the codebase (`server/src/radd/modules/access/__init__.py:19`), but `registries.tasks` has **zero readers** (verified whole-repo). Not a security hole (RADD-820 filters expired grants at resolution, `auth/grants.py:46`), but expired grant rows accumulate forever and the whole TaskSpec pipeline is a dead end.
- **Live client bug (RADD-701 class):** the SPA's `apiItemDocsPath` (`web/src/lib/constants/api-paths.ts:195`) builds `/items/{id}/docs`, but the backend route is `GET /items/{item_id}/pages` (`server/src/radd/modules/pages/router.py:463`). `itemPagesQuery` is used by `ItemPagesSection.tsx` and `routes/item-detail.tsx`, so the issue page's linked-pages section 404s today. The endpoint is not dead — the client is broken.
- **`GroupEvent.SYNCED` is a phantom automation trigger** — registered in the trigger catalog (`groups/__init__.py:16`, "Directory group synced") but never emitted anywhere (service emits only `MISSING`/`RESTORED`, `groups/service.py:348`). Any automation built on it can never fire. Either emit it from the sync or delete the registration.

---

## 1. Unused public functions / classes

### Priority modules (items, auth, views, events, fields, workflow) — very clean

| Location | Symbol | Conf. | Evidence / scope |
|---|---|---|---|
| `server/src/radd/modules/auth/types.py:510` | `permission_relation()` | CERTAIN | Repo-wide `-w` grep: def only (verified directly). Siblings (`split_permission` etc.) all live. ~3 lines |
| `server/src/radd/modules/auth/types.py:782` | `builtin_role()` + `_BUILTIN_BY_KEY` (:779) | LIKELY (test-only) | 10 refs total: def + dict + `tests/test_authz.py`. Product code iterates `BUILTIN_ROLES` (`auth/roles.py:62`). ~5 lines + test rewrites |
| `server/src/radd/modules/auth/scopes.py:66` | `TokenScope.projects_allowing()` | LIKELY (test-only) | Only `tests/test_service_accounts.py:203-206` (verified). Docstring claims it feeds the spec-114 MCP catalog; the catalog actually uses `mcp/requirements.py` `_project_permissions` + `authz.holds_base` — stale docstring. ~14 lines |
| `server/src/radd/modules/fields/router.py:137` | dead statement: `perms = await authz.effective_permissions(...)` in `field_writability` | CERTAIN | ruff F841 + manual check — result never used. **A wasted DB round-trip on a hot SPA path**, not just a dead local. 1 line |

### search, ai, attachments, jiraimport, mcp, settings, access, projects

| Location | Symbol | Conf. | Evidence / scope |
|---|---|---|---|
| `server/src/radd/modules/attachments/hosts.py:98` | `backup_roots()` | CERTAIN | Zero refs; backup uses `storage_hosts.default_snapshot()` (`backup/service.py:162`) instead (both ends verified). ~11 lines + now-unused `Path` import (:15) |
| `server/src/radd/modules/jiraimport/schemakeys.py:114,121` | `is_sprint_field()`, `is_epic_link_field()` | CERTAIN | Superseded by `find_by_schema_key()` (`runs.py:347`, `profile/accumulate.py:60-62`). ~10 lines |
| `server/src/radd/modules/jiraimport/ledger.py:128` | `summary()` | CERTAIN | Pre-flight endpoint calls `rollback.preflight()` which computes its own counts. Delete with the unused `ledger` import at `routers/pipeline.py:22`. ~9 lines |
| `server/src/radd/modules/access/service.py:81` | `subject_grants()` | CERTAIN | Zero callers (verified). ~10 lines |
| `server/src/radd/modules/access/service.py:92` | `subject_referenced()` | LIKELY | Zero code callers (verified). Named as the "deletion guard" in the spec-115 execution plan for RADD-832 — **RADD-832 has since shipped (group subjects live in `auth/models.py`/`grants.py`) without wiring it**, so the planned consumer never arrived. ~11 lines |
| `server/src/radd/modules/jiraimport/snapshot/store.py:63` | `issue_keys()` | LIKELY (test-only) | Only `tests/test_jira_snapshot.py:164`; docstring describes a consumer that doesn't exist. ~10 lines |
| `server/src/radd/modules/ai/embeddings/service.py:69` | `reset_availability_cache()` | LIKELY (test-only, by design) | Commented `# test seam`; only `tests/test_ai_embedder.py:79`. ~4 lines |

### Remaining modules + kernel + non-module backend

**Dead feature remnant — RADD-828 (tokened public form removed):**

| Location | Symbol | Conf. | Evidence / scope |
|---|---|---|---|
| `server/src/radd/modules/forms/service.py:193-194` | `if False and data.allow_public and form.public_token is None:` | CERTAIN | Literal unreachable branch (verified verbatim; the only `if False` in the tree). Delete branch + comment |
| `server/src/radd/modules/pages/public.py:104-150` | `deflect_public()` + `_semantic_public_ids` | CERTAIN | The tokened-form deflect seam; its consumer died with RADD-828. Also lets `pages/search.py:70` `pages_by_ids` drop its now-unused `public_only=True` param. ~47 lines |
| `server/src/radd/modules/forms/models.py:68` | `Form.public_token` column | CERTAIN (self-documented inert) | Only writer is the `if False` branch above; still serialized (`forms/schemas.py:175`, `web/src/lib/types/forms.ts:54`) but can never be non-null. Column + `FormRead.public_token` + TS field + drop migration |

**sso — an identity-listing surface that was never wired:**

| Location | Symbol | Conf. |
|---|---|---|
| `server/src/radd/modules/sso/service.py:218` | `identities_for_user()` | CERTAIN (verified zero refs) |
| `server/src/radd/modules/sso/service.py:413` | `google_kind()` | CERTAIN (verified) |
| `server/src/radd/modules/sso/types.py:45` | `SsoDenialReason` enum | CERTAIN (verified; denials go through plain strings at `router.py:83`) |

**Other modules:**

| Location | Symbol | Conf. | Note |
|---|---|---|---|
| `server/src/radd/modules/ldap/userimport.py:235` | `resolutions_by_email()` | CERTAIN | ~6 lines |
| `server/src/radd/modules/pages/page_access.py:181` | `restricted_page_ids()` | CERTAIN (verified) | "Drives the padlock in the UI" — no endpoint calls it; that half is unwired |
| `server/src/radd/modules/pages/access.py:39` | `require_space()` | CERTAIN (verified) | Routers call `authz.require(space_id=)` directly; docs/modules.md row lists it — trim the doc too |
| `server/src/radd/modules/mailintake/service.py:29` | `contacts_for_items()` | CERTAIN (verified) | Singular `contact_for_item` is alive; docs/modules.md still names the plural |
| `server/src/radd/modules/teams/types.py:4` | `ProjectRole` enum | CERTAIN | docs/modules.md:240 itself says "now-unreferenced … remove with the next teams change" |
| `server/src/radd/modules/forgejo/types.py:52-58` | `ForgejoEvent` enum (6 members) | CERTAIN (verified directly — zero `ForgejoEvent.` refs anywhere; `forgejo/__init__.py` registers no EventTypeSpecs) | ~8 lines |
| `server/src/radd/modules/screens/types.py:66` | `custom_field_key()` | CERTAIN | `is_custom_field`/`CUSTOM_FIELD_PREFIX` alive |
| `server/src/radd/modules/pluginmgr/boot.py:51` | `enabled_installable_paths()` | CERTAIN (verified) | Self-described "Back-compat" helper — direct no-backcompat-rule violation |
| `server/src/radd/modules/pluginmgr/discovery.py:78` | `path_for()` | CERTAIN | ~4 lines |
| `server/src/radd/modules/comments/parents.py:91` | `registered_types()` | LIKELY (test-only) | Only `tests/test_page_comments.py` |

**Kernel — never-wired contribution machinery** (all verified by direct grep):

| Location | Symbol | Conf. | Evidence / scope |
|---|---|---|---|
| `server/src/radd/kernel/specs.py:231` + `plugin.py:73` + `registry.py:92` | `ConsumerSpec` + `RaddPlugin.consumers` + `registries.consumers` | CERTAIN | Zero `ConsumerSpec(` instantiations anywhere; the dict is written from empty tuples and read by nothing. (Monitoring's consumer lag uses `events.service.consumer_status` — unrelated.) Spec class + field + registry dict + `kernel/__init__.py`/`sdk.py` exports |
| `server/src/radd/kernel/specs.py:220` + `plugin.py:76` + `registry.py:91` | `TaskSpec` pipeline | CERTAIN dead-end (+ operational bug) | One writer (`access/__init__.py:19`), **zero readers of `registries.tasks`** — so `sweep_expired_grants` (`access/service.py:228`) never executes. Wire a runner or delete the cluster and decide how the sweep runs |
| `server/src/radd/kernel/plugin.py:74-75` | `automation_actions`, `automation_conditions` fields | CERTAIN | Never set, never read (not even by `register_plugin`) |
| `server/src/radd/kernel/plugin.py:77-78` + `specs.py:353` | `settings_keys`, `settings_sections`, `SettingSectionSpec` | CERTAIN | Never set/read; `SettingSectionSpec` never instantiated; takes its `kernel/__init__.py` + `sdk.py` exports along |
| `server/src/radd/kernel/plugin.py` | `js_deps` (and `python_deps` read-side) | CERTAIN / LIKELY | `js_deps` never set or read; `python_deps` set twice but read by nothing — the manifest's "install step resolves them" has no implementation |
| `server/src/radd/kernel/registry.py:280` | `register_cascade()` | CERTAIN (verified — only a docstring cross-ref at `registry.py:264`) | Both real cascade users register via the manifest `cascades=` factory |
| `server/src/radd/kernel/registry.py:61` | `KernelRegistries.entities` dict | LIKELY (test-only — corrected from CERTAIN) | Written by `register_plugin`, read only by `tests/test_north_star.py:72-73` (verified); the loader iterates `plugin.entities` directly |
| `server/src/radd/kernel/sockets.py:98` | `active_provider()` | CERTAIN | Trivial alias of the live `provider()` |
| `server/src/radd/worker.py:17-45` | `LocalLoopBackend` + `LOCALLOOP` | LIKELY (test-only) | Registered on `Socket.TASK_BACKEND` (`capabilities/__init__.py:22`, verified) but only `tests/test_sockets.py` ever resolves it; all 18 real loops instantiate `PeriodicLoop` directly |

**SUSPECT — deliberate dormant seams (policy call, not mechanical):**
- `Socket.NOTIFIER`/`CONNECTOR`/`AI_PROVIDER`/`VCS_PROVIDER`/`ATTACHMENT_FILTER` + the `Notifier`/`AttachmentFilter`/`TaskBackend` protocols and the zero-ref `RoutingRule` Protocol (`kernel/sockets.py:65` — the live rule types register structurally without naming it): zero non-doc references, but `docs/plugin-platform.md` §13 documents them as intended seams.
- Five sdk-exported registrars with zero callers anywhere: `register_event_type`, `register_permission`, `register_crud_resource`, `register_capability`, `register_integration` — they are the semver'd external-plugin surface (out-of-repo plugins could call them), while the two registrars that ARE called (`register_relation`, `register_relation_domain`) are not sdk-exported. The convention has inverted; prune or re-export deliberately.

## 2. Unused endpoints

451 routes enumerated with resolved prefixes; matched against `web/src` (constants + ~130 `api*Path()` helpers + template literals, binary-safe `-a` greps), `web/packages/plugin-sdk` (binary-safe), module UI remotes (`server/src/radd/modules/*/ui/src`), `server/tests`, `sdk/`, `scripts/`, `server/scripts/`, `docs/`. Every verdict below was individually hand-verified after the automated pass.

### CERTAIN dead (zero callers anywhere, including tests)

| Route | Location | Scope / note |
|---|---|---|
| `POST /jira/plans/{plan_id}/resuggest` | `server/src/radd/modules/jiraimport/routers/pipeline.py:94` | Handler ~15 lines |
| `POST /pages/reindex-links` | `server/src/radd/modules/pages/router.py:402` | SPA constant `pageReindexLinks` (`web/src/lib/constants/api.ts:151`) defined-unused — delete both; docs/modules.md mentions it (RADD-713) |
| `GET /page-spaces/{space_id}/export` | `server/src/radd/modules/pages/router.py:320` | SPA uses page-level export only |
| `GET+POST /page-templates`, `PATCH+DELETE /page-templates/{id}` | `server/src/radd/modules/pages/router.py:157,172,183,197` | No client, no tests. `pageTemplatesQuery` (`web/src/lib/queries/pages.ts:90`) defined-unused. **Caveat:** `POST /pages` consumes templates server-side (RADD-712), so today templates can only be authored via curl — deleting the family also kills `pages/templates.py` + the `PageTemplate` model; product decision, not mechanical |
| `PATCH /service-accounts/{account_id}` | `server/src/radd/modules/auth/router.py:531` | `apiServiceAccountPath` (`web/src/lib/constants/api.ts:217`) defined-unused (only the keys helpers are imported — verified) |
| `POST /backups/{name}/verify` | `server/src/radd/modules/backup/router.py:281` | No web/tests/scripts callers |
| `GET /backups/runs` (list) | `server/src/radd/modules/backup/router.py:136` | SPA polls single runs only (`web/src/lib/queries/activity.ts:138`) |
| `GET /leave/users/{user_id}` | `server/src/radd/modules/leave/router.py:62` | SPA uses `/leave`, `/leave/mine`, `/leave/holidays` only (handler only — `list_for_user` is shared) |
| `GET /grants/resources` | `server/src/radd/modules/access/router.py:45` | Only a comment in `web/src/lib/types/grants.ts:39` and the docs row reference it; `AccessGrantsEditor` never calls it (verified) |
| `POST /plugins/{plugin_id}/install`, `POST /plugins/{plugin_id}/uninstall` | `server/src/radd/modules/pluginmgr/router.py:59,114` | SPA calls enable/disable only (`plugins.tsx:40-44`); tests exercise the service directly. Caveat: deleting uninstall leaves no surface to uninstall an installable plugin |

### LIKELY dead (test/demo-only)

| Route | Location | Evidence |
|---|---|---|
| `POST /jira/preview` | `server/src/radd/modules/jiraimport/router.py:143` | Only `tests/test_jira_discovery.py`; SPA constant `jiraPreview` (`api.ts:45`) unused; superseded by the spec-100 snapshot flow |
| `GET /webhooks/{endpoint_id}/deliveries` | `server/src/radd/modules/webhooks/router.py:56` | Only `server/scripts/demo_webhooks.sh:81` |
| `GET /public/pages/search` | `server/src/radd/modules/pages/public_router.py:43` | Zero HTTP callers; tests hit `kb.search_public` directly (keep the service — deflection composes over it) |

### Decide-clusters (not mechanically dead)

- **`/webhooks` CRUD (POST/GET/PATCH/DELETE + deliveries)** — `server/src/radd/modules/webhooks/router.py:21-56`: **no SPA management UI exists at all** (verified: no settings page, no query file); exercised only by `demo_webhooks.sh`, `test_quiet_events.py`, and documented in docs/modules.md/deploy.md. Either an intentional API-only surface (keep, document as such) or a UI gap.
- **`GET /ai/local-embed`** — `server/src/radd/modules/ai/admin_router.py:147`: zero SPA/test callers, but `docs/deploy.md` documents it as the operator's catalog of local embedding models. SUSPECT — keep or wire into Settings → AI.

### Verified alive despite looking dead (recorded so the deletion pass doesn't touch them)
`/plugins/contribution-settings` GET+PUT (plugin-sdk `slots.tsx:242,268` — binary-file grep trap), `/items/{id}/participants*` (participants UI remote), view members PUT/DELETE (`web/src/routes/view.tsx:295`), storage host default/health/move (`HostsPanel.tsx`, `MoveJobProgress.tsx`), cycles complete/stats, dashboard sharing/transfer/widgets, canned render (`CommentsThread.tsx:355`), comments resolve/reopen (`PageInlineComments.tsx:70`), automations run (`quick-actions.ts:113`), roles impact (`roles.tsx:133`), SSO provider test (`ProvidersPanel.tsx:93`), `/events` + `/events/{id}` (SDK, spec 44), `/mcp` (spec 45/114), `/auth/oidc/callback` (browser redirect leg), webhook receivers (`/integrations/forgejo|gitlab|alertmanager`), public form/KB/CSAT tokened surfaces, ~~`/health`~~ *(correction: no `/health` route exists — see editorial note at top)*, `/ws` (`realtime.ts:97`), kernel auto-CRUD (milestones).

## 3. Orphaned modules

**None.** All 51 modules in `server/src/radd/modules/` are in the default `Settings.modules` assembly (`server/src/radd/config.py:322-375`) — including `screens`, `weblinks`, `groups`, `capabilities`, `gitlab`, `googlechat` (all verified loaded; `screens` additionally verified SPA-consumed via `GET /screens/effective`). The sole exception is **`milestones`**, which is deliberately not bootstrapped: it is the documented installable-plugin north star (`config.py:380` `installable_plugins`, docs/modules.md §north-star) — status noted, not a deletion candidate.

## 4. Unused models / columns

| Location | Column | Conf. | Evidence / scope |
|---|---|---|---|
| `server/src/radd/modules/forms/models.py:68` | `Form.public_token` | CERTAIN | See §1 RADD-828 cluster (only writer is `if False`). Drop column + serializations + migration |
| `server/src/radd/modules/jiraimport/models/run.py:43` | `JiraRun.plan_snapshot` | LIKELY (write-only) | Written once (`routers/pipeline.py:142`), never read, never serialized (verified). Possibly intentional forensics — decide, then drop + migration |
| `server/src/radd/modules/slas/models.py:59,62` | `SlaItemState.response_due_at`/`resolution_due_at` | SUSPECT — **do not delete without checking** | Written via `setattr(f"{prefix}_due_at")` (`evaluation.py:269`); served values are recomputed in `timers.py`. Flag only |

Whole tables: **none dead.** All 110 mapped tables have live service code. Cleared explicitly: `workspaces`/`workspace_memberships` were hard-dropped by raw SQL in migration `f4a9c31e77d2`; the spec-92 drops (`field_permissions`, `builtin_field_rules`, `view_shares`, `dashboard_shares`) have no surviving models; `milestones` is the EntitySpec auto-table.

## 5. Unused config / env vars

- `server/src/radd/config.py:229` — **`jira_page_size`** — CERTAIN. Verified: `jiraimport/client.py` uses its own `MAX_PAGE_SIZE = 100` constant; `settings.jira_page_size` is read nowhere. (`RADD_JIRA_PAGE_SIZE` is still documented in `docs/specs/90-*.md` — historical, fine.)
- All 21 other zero-`settings.X`-grep fields are **ALIVE via dynamic dispatch**: the settings cascade reads them through `getattr(_config, config_attr or key.value)` (`modules/settings/types.py:101`) — verified each against `SettingKey` values + `config_attr=` overrides. This is the audit's biggest dynamic-dispatch trap; do not delete any `SettingKey`-backed field on grep evidence.
- `server/src/radd/config.py:208` — `forgejo_merge_transition_state` — alive but self-annotated "spec 112 replaced this"; it survives as a deliberate fallback in `forgejo/router.py:196`. Under the no-backcompat rule this is a deletion candidate (SUSPECT/deliberate; cross-ref `06-backcompat-hacks.md` A2).
- Stale env documentation (docs are required-current per rule 3): `RADD_PLUGIN_ASSETS_DIR` in `docs/modules.md:26` — no such setting exists; bundles are served from per-plugin dirs via `registries.plugin_ui_dirs` (the "stable `plugin-assets/` dir" sentence is stale too). `RADD_LOCAL_EMBED_CACHE` in `docs/deploy.md:62` and the `ai/localembed.py:15` docstring — the real env var is `RADD_AI_LOCAL_EMBED_CACHE` (pydantic prefix + `ai_local_embed_cache`).

## 6. Unused Pydantic schemas

All verified by direct grep (zero refs outside their own definitions):

**Spec-90 wizard leftovers, `server/src/radd/modules/jiraimport/schemas.py`** (superseded by the spec-100 rebuild; ~75 lines + the `ImportStage` import at :12): `ImportPlanCreate` (:225), `ImportPlanUpdate` (:234), `ImportPlanRead` (:244), `SuggestMappingsRequest` (:257), `MappingProblemRead` (:264, only consumer is the dead `ValidateMappingsResponse`), `ValidateMappingsResponse` (:269), `ImportRunStart` (:277), `ImportRunRead` (:283) — plus **`ImportStage` enum, `jiraimport/types.py:346`** (~14 lines; its only reference is dead `ImportRunRead.stage`). `FieldMappingEntry`/`InferredFieldRead` in the same file are alive. Side finding: `web/src/lib/types/jira-import.ts:472` declares a TS `ValidateMappingsResponse` mapping to no surviving endpoint.

**RADD-828 leftovers, `server/src/radd/modules/forms/schemas.py`** (~27 lines): `PublicFormSubmit` (:229), `PublicDeflectDoc` (:248, cascade), `PublicDeflectResponse` (:260). `PublicFormRead`/`PublicFormField`/`PublicSubmitResult` are alive (spec-73 portal).

**Singles:** `SsoIdentityRead` (`sso/schemas.py:110`, ~13 lines — stale "Settings → Users, profile" docstring, nothing imports it; pairs with the dead `identities_for_user`); `TeamAccessRead` (`auth/schemas.py:181`, ~7 lines — its field types are used elsewhere and stay).

## 7. Unreachable code, phantom event types, unused imports

- **Unreachable:** `server/src/radd/modules/forms/service.py:193` `if False and …` (verified; §1). A full AST scan for statements after `return`/`raise`/`continue`/`break` across `src/radd` found nothing else.
- **Registered-but-never-emitted event types** (cross-checked all `*Event` StrEnums against every emit site, string-value comparisons, web, sdk):
  - `FieldEvent.RULES_UPDATED = "field_rule.updated"` (`fields/types.py:49`) + `FieldEntity.FIELD_RULE` (`:54`) — CERTAIN; spec-92 leftovers of the dropped builtin_field_rules. Zero refs outside types.py (verified).
  - `ForgejoEvent` — whole enum dead (§1).
  - `GroupEvent.SYNCED = "group.synced"` — registered as an automation trigger (`groups/__init__.py:16`), never emitted (verified) — phantom trigger or a missing emit; decide which.
- **Unused imports (ruff F401, manually filtered):** 39 genuinely dead import lines. Notable cluster: `server/src/radd/modules/attachments/gc.py:17-24` (5 imports left over from the pre-RADD-745 consumer-loop implementation). Excluded as alive: `sdk.py` re-exports (the public facade), `pages/__init__.py:12-13` binding imports (side-effect registrations — add `noqa`/redundant-alias instead), `forgejo/__init__.py` models (already `noqa`'d for Alembic). Full list: `ruff check --select F401` minus those three groups.
- **F841 (23 hits):** all but one are deliberate 404-before-403 existence checks (`x = await service.get_x(...)` before `authz.require`) — change to bare `await` if desired, not deletions. The exception is the fields/router.py:137 finding in §1.

## 8. Leftovers from completed refactors

- **Backend is clean** on the named removals: no code references to Crepe/Milkdown (one contract-note comment in `ai/editor.py:3` — accurate), MinIO (the `minio` pip package is the live S3 *client* in `attachments/clients.py:139`; the archived MinIO *server* appears only in comments), `field_permissions`/`builtin_field_rules`/`view_shares` tables (models and migrations all gone), workspace entity (comments and local variable names only — verified every hit).
- **Legacy-named but alive** (rename-candidates, not dead): `_check_builtin_field_rules` (`items/service/visibility.py:297` — now backed by access grants), `ViewShareEntry`/`ViewShareRead` (`views/schemas.py:107,234` — the live wire shape over access-grants).
- **Actual leftovers to delete:** `enabled_installable_paths` (§1), `forgejo_merge_transition_state` fallback (§5), `fields/schemas.py:30` `_fold_legacy_scope` — a live validator that exists solely to accept the pre-spec-91 single-`project_id` payload shape (verify the SPA no longer sends it, then delete the shim + alias).
- **Documentation drift in required-current files:** docs/modules.md — `RADD_PLUGIN_ASSETS_DIR`/`plugin-assets/` (§5), `contacts_for_items`, `ProjectRole` ("remove with the next teams change" — that change is now), `require_space` in the RADD-791 seam list, and the forms/pages rows still describing the removed public-form/deflect surface (RADD-828).
- **Frontend side findings** (cross-ref `05-dead-code-frontend.md`): stale `apiItemDocsPath` (`/items/{id}/docs` — the live bug above), unused `apiServiceAccountPath`, `jiraPreview`, `pageReindexLinks` constants, unused `pageTemplatesQuery` ≈ 80 lines.

## 9. Unused deps in `server/pyproject.toml`

**None.** Every declared dependency verified imported: `minio` (`attachments/clients.py:139`, lazy), `pillow` (`attachments/thumbnails.py:82`), `pyjwt` (`sso/service.py`), `ldap3` (ldap module), `fastembed` (optional extra, `ai/localembed.py`), `httpx`/`pwdlib`/`alembic` (alembic.ini + migrations)/`python-multipart` (FastAPI upload parsing) all in active use.
