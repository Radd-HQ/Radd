# Backwards-Compatibility Audit — Radd (``), 2026-08-05

**Scope:** `server/src`, `server/migrations` (runtime leakage only), `web/src`, `web/packages`. Read-only. Baseline rule: **no backcompat until V1** — every compat mechanism is a finding; the report states what deleting it costs.

## Executive summary

**19 real compat mechanisms found** (7 server runtime shims, 2 dual-shape parsers, 3 old-field wire emissions, 5 frontend compat paths, 2 DB null-tolerance dual paths), plus 4 dead compat aliases with **zero in-repo callers**. The documented spec-92 table drops (`field_permissions`, `builtin_field_rules`, `view_shares`) are verified — all three are gone. Migration-internal legacy handling (spec 107 rule rewrite, spec 86 hard drop) stays inside migrations and does not leak into runtime.

**Top offenders:**
1. **Attachments pre-102 alias routes** — kept for consumers that no longer exist.
2. **Forgejo merge-transition env-state fallback** — an explicit "existing deployment keeps its old behaviour" dual path, contradicting both the spec-112 pipeline and the seed-only env rule.
3. **`UserSource.UNKNOWN` lazy migration** — an enum member + server default kept so pre-spec-84 rows upgrade on next login instead of in one migration.
4. **A cluster of dead wire aliases** (`ViewCreate.shared`, `ProjectTeamAttach.role`, `FieldDefinitionCreate.project_id`, pluginmgr helpers) — each verified to have no remaining sender.

Counterpoint worth recording: the codebase also contains textbook applications of the rule — `TeamChange` values retired **without** reader-side aliases (`server/src/radd/modules/teams/types.py:27-30`), RADD-701's `doc_page`→`page` rename shipped with no server-side route aliases, and spec 107 rewrote stored workflow rules in the migration so runtime code accepts only the new shape.

---

## (a) Runtime compat shims (server)

### A1. Attachments: pre-102 item alias routes — **Medium**
`server/src/radd/modules/attachments/router.py:158-172` (header comment also at `:1-2`).
`POST /items/{item_id}/attachments` and `GET /items/{item_id}/attachments` delegate to the canonical polymorphic `/attachments` routes. The docstring claims "every pre-102 consumer (SDK/MCP/importer) still calls" them — **verified false today**: the SPA uses `apiAttachmentsPath()` = `/attachments` (`web/src/lib/constants/api-paths.ts:165`), the MCP module registers no attachment tool, `jiraimport` uses the blob API, `sdk/` never touches attachments, and no test hits the alias paths.
**Protects:** nothing in-repo; hypothetically external extensions.
**Removal cost:** delete two handlers + the stale docstring. Nothing else.

### A2. Forgejo: merge-transition falls back to the spec-47 env state name — **Medium**
`server/src/radd/modules/forgejo/router.py:181-198` (`_transition_merged`).
When a project has not configured the spec-112 release pipeline (`waiting_state_id` is None), the handler resolves the target state by **name from `settings.forgejo_merge_transition_state`** — the comment says outright: "so an existing deployment keeps its old behaviour." This is a live old/new dual path: two config systems (project settings vs env var) can produce different transitions for the same event.
**Protects:** deployments that set the spec-47 env var and never opened the spec-112 project settings.
**Removal cost:** those projects' merged PRs stop auto-transitioning until an admin sets the pipeline states — a settings visit, no migration.

### A3. Forgejo: capability check still reads the seed-only env secret — **Medium-Low**
`server/src/radd/modules/forgejo/__init__.py:26`: `check=lambda: {"enabled": bool(settings.forgejo_webhook_secret)}`.
Since spec 111, connections are `forgejo_connections` rows and the env secret is documented SEED-ONLY (`service.seed_from_env`, correctly seed-once at `service.py:204-228`). But the capability pill keys "enabled" off the env var at runtime — an instance whose connection was created in the UI (no env) reports the connector disabled; an instance that deleted the seeded row but kept the env reports it enabled.
**Removal cost:** change the lambda to count active connection rows (needs the snapshot idiom the storage capability already uses at `attachments/__init__.py:20-28`). No data cost.

### A4. `UserSource.UNKNOWN` — enum member + server default kept for pre-spec-84 rows, upgraded lazily — **Medium-Low**
`server/src/radd/modules/auth/types.py:25` (`UNKNOWN = "unknown"  # pre-spec-84 SSO-only rows (upgraded on next login)`), `server/src/radd/modules/auth/models.py:41` (`server_default=UserSource.UNKNOWN.value`), upgrade site `server/src/radd/modules/sso/service.py:357-361`.
A lazy migration: old rows keep `unknown` until their owner happens to log in via SSO. Users who never log in again stay `unknown` forever.
**Removal cost:** one throwaway migration deriving `source` from `user_identities`/LDAP linkage (or defaulting to `local`), drop the enum member and the lazy-upgrade branch, and fix the stale `server_default`.

### A5. SLA weekly report folds duplicate bookkeeping rows from the "pre-spec-63 evaluate-all era" — **Low**
`server/src/radd/modules/reporting/service.py:395-405`. The reader tolerates several `SlaStateRow`s per item because pre-63 code wrote them that way, folding earliest-met/any-breach at read time on every report render.
**Protects:** un-deduplicated pre-63 rows in existing databases.
**Removal cost:** one throwaway dedupe migration; the fold loop then collapses to a dict build. (Verify current writers really are one-row-per-item first — if not, this is a live invariant, not compat.)

### A6. LDAP: raw-env search-base fallback kept beside the settings cascade — **Low**
`server/src/radd/modules/ldap/service.py:256-262`: `base=None` → `user_search_base()` (raw env), explicitly "kept for `scripts/import_ad_users.py`, which has no session." RADD-846 moved the connection into cascade-backed settings; this keeps a second, session-free path that can silently disagree with Settings → Directory.
**Removal cost:** give the script a DB session (it already needs the DB to import users) and delete the raw-env branch.

### A7. Storage hosts: `root_dir = ""` means "read `settings.attachments_dir` at runtime" — **Low**
`server/src/radd/modules/attachments/schemas.py:40` (`""` = env default), consumed at `clients.py:81` and `hosts.py:102` (`host.root_dir or settings.attachments_dir`), plus `backup/service.py:168`. A host **row** exists but the env still decides where bytes live — the exact "row exists yet env is still read" pattern the seed-only rule exists to prevent. The migration/seeder both write a concrete `root_dir` (`hosts.py:284`, migration `164d25776678` line 141), so the fallback serves only hand-created rows with the empty-string sentinel. Related cosmetic: `projects/router.py:79` falls back to `settings.attachment_storage` for the status pill, and `attachments/__init__.py:23` keeps `backend`'s "pre-102 meaning".
**Removal cost:** require a non-empty `root_dir` on filesystem hosts (one validator + a backfill UPDATE for any `''` rows).

### Dead server-side compat aliases (all **Low**, zero callers verified)
- `server/src/radd/modules/pluginmgr/service.py:118-121` — `_require_installable`, labeled "Back-compat alias." No callers anywhere.
- `server/src/radd/modules/pluginmgr/boot.py:51-59` — `enabled_installable_paths`, "Back-compat". No callers.
- `server/src/radd/modules/teams/types.py:4-11` — `ProjectRole` "Legacy fixed role ladder… survives only as the fields module's `min_read_role`/`min_write_role`" — those columns no longer exist (spec 92); the enum has **zero references** outside its own file.
- `server/src/radd/modules/automations/types.py:19-20` — `MANUAL_TRIGGER` "Legacy alias — the sentinel predates the enum"; two router usages could read `AutomationTrigger.MANUAL` directly.
**Removal cost for all four:** deletion (plus two one-line router edits).

## (b) Dual-shape parsers / normalizers

### B1. `FieldDefinitionCreate.project_id` — legacy single-scope alias folded into `project_ids` — **Low**
`server/src/radd/modules/fields/schemas.py:13-16, 29-36` (`_fold_legacy_scope`). Accepts the old singular param and upgrades it on parse. **No sender remains**: the SPA sends `project_ids` (`web/src/lib/types/fields.ts:79,101`), and `jiraimport` builds `project_ids=[...]` (`server/src/radd/modules/jiraimport/provision.py:156`).
**Removal cost:** delete the field + validator.

### B2. `ProjectTeamAttach.role` — role-KEY accepted beside `role_id` — **Low**
`server/src/radd/modules/teams/schemas.py:79-84`, folded at `server/src/radd/modules/teams/service.py:370-373` ("compat: role key, defaulting to the builtin member role"). The SPA sends `role_id` (`web/src/components/settings/TeamPanel.tsx:137`); no script/test sends `role`.
**Removal cost:** delete the field; keep the implicit member default if desired (that half is default semantics, not compat).

### B3. `ViewCreate.shared` — pre-spec-57 boolean alias for `global_access` — **Low**
`server/src/radd/modules/views/schemas.py:179-183`, folded at `server/src/radd/modules/views/service.py:601-602` ("Pre-spec-57 alias: shared=true meant globally-visible"). No sender found in web, tests, or sdk.
**Removal cost:** delete field + one line.

## (c) API aliases & old field names on the wire

### C1. `AttachmentRead.item_id` — legacy mirror of `entity_id` — **Low**
Emitted via `server/src/radd/modules/attachments/schemas.py:16` backed by the property at `models.py:117-122` ("API back-compat + events"). The SPA type carries it only to document it as legacy (`web/src/lib/types/attachments.ts:28-29`) and never reads it. Note the split: the **event-payload** `item_id` (`service.py:111-113`) has live consumers (notify/automation item-scoping) — only the REST field is vestigial.
**Removal cost:** drop the schema field; keep the property for events (or inline it there).

### C2. `CommentRead.item_id` — same mirror after comments went polymorphic (RADD-717) — **Low**
`server/src/radd/modules/comments/schemas.py:44-50`: "the entity id when the parent IS an item, else null — so every existing issue-side consumer keeps working unchanged." The SPA reads comments off the item route and never dereferences `comment.item_id`.
**Removal cost:** drop the field; clients read `entity_type`/`entity_id`.

### C3. `AiStatus.enabled/provider/model` — "old fields kept for back-compat" — **Low**
`server/src/radd/modules/ai/types.py:146-156`; `server/src/radd/modules/ai/service.py:60-64` ("back-compat: pre-101 frontends read only `enabled`"). Nuance: `enabled` is still read by the current SPA (CommandPalette, AiSection), so it has live semantics; `provider`/`model` on the status payload appear unread anywhere in `web/src` (the settings pages use `/ai/providers`/`/ai/roles`).
**Removal cost:** drop `provider`/`model` from `AiStatus`; re-document `enabled` as current API rather than compat.

## (d) Frontend compat

### D1. `useEditorAi` tolerates a pre-spec-101 backend — **Medium-Low**
`web/src/components/editor/ai.ts:58-61`: `features` is optional-chained *deliberately* because "a pre-spec-101 backend returns {enabled, provider, model} with no features map at all." The SPA and backend ship in one image — there is no deployment where this frontend meets a pre-101 backend.
**Removal cost:** make `features` required in the type, drop the `?.` — nothing breaks.

### D2. Legacy route redirects — **Low** (three distinct mechanisms)
- `/p/$projectKey/roadmap` — a whole component kept to redirect pre-spec-79 links: `web/src/routes/roadmap.tsx:1-40`, registered at `web/src/router.tsx:247-253`, constant documented at `web/src/lib/constants/routes.ts:94-96`.
- `/settings/members` → Users redirect: `web/src/router.tsx:455-462`, `routes.ts:27`.
- `/settings/leave` → Profile redirect: `web/src/router.tsx:584-591`, `routes.ts:58-60`.
- Pre-702 `/docs/<uuid>/<uuid>` URL routes "kept as routes so they REDIRECT rather than 404": `web/src/lib/constants/routes.ts:195`, landing in `web/src/routes/page-space.tsx:19-29`. (The slug-OR-id addressing itself also serves live id-only callers — search results — so only the extra route registrations are pure compat.)
**Protects:** old bookmarks/inbound links only.
**Removal cost:** delete routes/components; old links 404. Pre-V1 with one public instance, that cost is a handful of stale bookmarks.

### D3. `ViewList` legacy queue render path is dead at its only call site — **Low**
`web/src/components/views/ViewList.tsx:52-53` ("Queue rendering… Legacy path only — a queue with `listColumns` renders those as columns") and the `queue && <QueueRowMeta …>` branch at `:471`. The component's **single** call site (`web/src/routes/view.tsx:1186-1207`) always supplies `listColumns` (defaults resolved at `:437-441`), so the slot-cluster/`QueueRowMeta` branch cannot render there.
**Removal cost:** delete `QueueRowMeta` + the `queue` prop threading (confirm no swimlane reuse first).

### D4. `applyRankChain` kept `async` "for call-site compatibility" — **Info**
`web/src/components/roadmap/useRoadmapEditing.ts:416-419` — a function signature preserved after its body stopped awaiting, with an eslint-disable to silence the linter that noticed. Trivial internal shim; fix the call sites instead.

## (e) DB leftovers

- **Verified clean:** `field_permissions` dropped (`server/migrations/versions/6fc5f7c71481…py:46`), `builtin_field_rules` dropped (`3d1e2f0f3823…py:28`), `view_shares` dropped (`925809931622…py:32`). No runtime code references the tables (only docstrings and a grants-backed function that kept the old name — see (g)).
- **E1. `teams.owner_id` NULL on pre-87 rows → atom-fallback dual path** — **Low**. `server/src/radd/modules/teams/models.py:23-28`: "NULL on pre-87 rows — those fall back to the team.update atom." New teams always get an owner (`service.py:33` — `owner_id=data.owner_id or actor_id`), so NULL is purely pre-migration residue keeping a second authz branch alive. **Removal cost:** one migration assigning owners (e.g. first manager, else an admin) + delete the fallback branch. *(Contrast with views, where owner-less is a live design — see (f).)*
- **E2. `users.source` `server_default='unknown'`** — `server/src/radd/modules/auth/models.py:41` — part of finding A4; the server default should not be the legacy sentinel.
- **E3. `storage_hosts.root_dir` empty-string sentinel** — part of A7.
- **Not a leftover:** `api_tokens.scopes` NULL = full authority (`server/src/radd/modules/auth/models.py:104`) — NULL is the documented *current* default for personal tokens, not a legacy state.

## (f) Deliberate-and-documented tolerance (kept)

- **Spec-68 key-alias resolution** (`server/src/radd/modules/items/service/read.py:152-157`, `queries.py:155`): a bulk-moved item resolves under its old key, responses carry the current key. A permanent product feature (GitHub-rename semantics), not compat.
- **Views: owner-less views are LIVE, not legacy — but the labels say otherwise.** `defaults.py:23-47` seeds every project's Board/List/Planning/Roadmap with `owner_id=None`, and the "LEGACY owner-less" atom-fallback branches (`views/models.py:18-20`, `service.py:543-575, 601-602 area, 743`, `router.py:114,141`, mirrored in `web/src/components/views/ViewModal.tsx:90`, `web/src/lib/types/views.ts:144`) are exactly what makes those seeded views administrable. Keep the mechanism; **fix the naming** — calling a load-bearing path "legacy" invites someone to delete it.
- **Card designer loose validation** (`web/src/lib/card-layout.ts:66-110`, server `views/service.py:404`) and **bucket-order loose coupling** (`views/models.py:34-39`) — documented graceful degradation of stored user config. The `v: 1` discriminator has no version branching anywhere; it is one speculative field, harmless.
- **Jira markup rendering** (`web/src/lib/jira-markup.ts`, `web/src/components/editor/RichViewer.tsx:66`, `web/src/lib/markdown.tsx:34` `<br>` handling): tolerance of imported/pasted **user data**, explicitly in-scope forever for a Jira importer.
- **Pages backlink indexer accepts pre-702 UUID link forms** (`server/src/radd/modules/pages/backlinks.py:17-24`): stored page bodies legitimately contain old-form links; parsing them is user-data tolerance. (A one-shot body rewrite could retire it, but bodies are user content — leaving them is defensible.)
- **Seed-only env pattern** — verified genuinely seed-once for AI (`ai/registry.py:317-328`), SSO (`sso/registry.py:266-296`), Forgejo connection (`forgejo/service.py:204-228`), storage host (`attachments/hosts.py:288-296`), Jira connection. The A3/A2 findings above are the two places the pattern is violated.
- **Settings cascade with env as ultimate default** (`settings/types.py:36,100`, incl. the RADD-846 LDAP keys at `:49-60`) — documented design (env = instance default, DB rows override). Note the design tension: for *connections* it quietly preserves old deploys ("an existing deploy keeps working untouched") where sibling specs chose seed-once; a future consolidation could move LDAP to seed-once too.
- **`schema_version.py`** (`server/src/radd/schema_version.py`) — deliberate backup/restore data-compat versioning (spec 99), with a test forcing a changelog entry per bump.
- **Kernel/plugin semver gates** (`server/src/radd/kernel/loader.py:20-42`, `web/packages/plugin-sdk/src/version.ts:16-19`) — platform API versioning for third parties, the one place backward-compat is the contract.
- **Workflow guard "legacy failure strings"** (`workflow/guards.py:61-68`) — a UX wording choice ("an assignee is required" reads better), not a parse path.
- **RADD-854 category keys coinciding with old enum values** (`workflow/schemas.py:12-15`) — compat achieved by *naming*, zero code kept.
- **LDAP import `resolutions` default** (`ldap/schemas.py:63-68`) — an absent entry defaulting to create-or-link is sensible default semantics; the "backward compatible" phrasing oversells it.

## (g) False positives checked and cleared

- `server/src/radd/backup/*` "Compatibility"/"incompatible backup" — live restore-safety checks (spec 99), not legacy shims.
- "OpenAI-compatible"/"S3-compatible" across `ai/*`, `attachments/clients.py`, config, web settings — protocol descriptions.
- "Backward edge" in `events/router.py:8`, `workflow/service.py:106`, `auth/roles.py:158` — module-dependency-direction commentary, no compat code.
- `jiraimport/transform.py:193+` `legacy = issuemap.map_issue(...)` — a variable name for the still-live value-decoder; spec 100 already deleted the actual legacy tables (`types.py:373`, `issuemap.py:24`).
- `jiraimport` `PARENT_INCOMPATIBLE` — a problem-report kind, wordplay only.
- `dashboards/service.py:8,295` — explicitly documents that the owner-less fallback does **not** exist there; rule applied.
- `forms/service.py:324-326` `_REPORTER_UNSET` — omitted-vs-null sentinel; "pre-62 behavior" just names the default.
- `reporting/schemas.py:59` / `service.py:231` "exact pre-70 shape" — describes count-mode semantics staying int; no old-format branch.
- `comments` `CommentVisibilityTeam` no-rows default (`models.py:49-52`) — live "unnarrowed" semantics, not row-vintage tolerance.
- `_check_builtin_field_rules` (`items/service/visibility.py:297`) — grants-backed since spec 92; only the *name* still says `builtin_field_rules` (rename-nit, no mechanism).
- `search/deflect.py:30` "previously resolved" — domain vocabulary.
- Roadmap/timesheet "backward" (`Connectors.tsx:62`, `timesheet.ts:54`, `model/dates.ts:34`) — spatial/temporal direction.
- `items/listing.py:4` "sequential-scan for now", `views/models.py:90` "0 = fetch order for now" — TODOs, not compat.
- `web/src/lib/url-state.ts` `?s=` short-link fallback + localStorage GC — a live length-limit feature; **no localStorage key-migration code exists anywhere in `web/src`** (checked every `getItem`/`removeItem` site).
- `useRoadmapViewport.ts:11`, `settings/states.tsx:333`, `comments/schemas.py` polymorphic notes — descriptive "keeps working" language over current designs.
- `schema_version` `SCHEMA_VERSION = 1` with no compat branches — nothing yet leans on it at runtime.
- MCP module — no tool aliases, no renamed-tool tolerance; `visible_catalog` enum→string degradation is a documented scale valve, not compat.
- `ldap/types.py:29`, `attachments/parents.py:38`, `auth/authz.py` "used to…" comments (~20 sites) — history notes on code that was *replaced*, old path gone.
- Migrations `a107c0nd1t10n` (legacy check rewrite) and `f4a9c31e77d2` (workspace hard drop) — legacy handling fully contained in migrations; runtime enums (`TransitionCheck`) carry only the new vocabulary.
