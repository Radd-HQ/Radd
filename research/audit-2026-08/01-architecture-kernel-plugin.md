# Radd kernel/plugin architecture audit — 2026-08-05

## Executive summary

- **1,080 cross-module import statements** across 53 modules; all 53 modules expose `plugin = RaddPlugin` and load through the kernel loader from `config.Settings.modules` — **no legacy-wired modules remain**.
- **78 imports of another module's `models.py` beyond the spine exception** (User/Project) — the single largest violation class. 13 of them are `events.models.Event` (a missing public re-export); ~20 are `items.models.WorkItem` from feature modules; the rest reach into workflow/fields/teams/access/groups/pages/labels/attachments/comments/itemtypes/cycles/releases/timelogging tables.
- **38 cross-module `ForeignKey` references beyond `users`/`projects`** — the de-facto spine is really `work_items` (14 modules), `teams` (8), `states`, `roles`, `labels`, `issue_types`, `groups`, `page_spaces`; the declared spine exception no longer describes the codebase.
- **The kernel is clean at module-load time but imports `auth`, `projects`, and `events` at runtime** inside `kernel/entities.py` CRUD handlers — a deliberate but real mechanism→policy inversion.
- **Two central enums defeat the contribution registries**: `auth/types.py::Permission` hardcodes every core module's atoms and `settings/types.py::SettingKey` hardcodes AI/CSAT/release/timesheet/LDAP keys, while the kernel registries that exist for exactly this are used only by `milestones`.
- **The MCP kernel registry (`McpToolSpec`, RADD-640) has exactly one client** (`milestones`); the 19 core tools are hardcoded in `mcp/tools.py` importing ten modules, and `pages` is special-cased via an importlib reflection bridge.
- **Dependency declarations have drifted badly**: 30 of 53 modules import modules they do not declare in `depends_on` (worst: `auth` imports 6 undeclared feature modules; `items` 6; `jiraimport` 7), and there are at least four genuine import **cycles** (items↔workflow, items↔linktypes, items↔timelogging, groups↔teams, auth↔events).
- **The frontend host is architecturally clean** for plugins (generic loader, catch-all route, slot registry, no plugin named in host code); builtin view/widget types are enum-special-cased in the host, a two-tier design rather than a violation.
- Raw-SQL cross-ownership: `jiraimport/rollback.py` deletes from seven other modules' tables by name; `ai/embeddings/service.py` counts rows in `search_index` and `pages` by raw SQL; `search/indexer.py` reads `work_items` directly (self-documented as a "tolerated inward read").

---

## 1. Kernel policy leaks

**Major — `server/src/radd/kernel/entities.py:171,178,181,190,225,234`**
The generic Entity CRUD factory defers-imports `radd.modules.auth.deps.CurrentUser`, `radd.modules.auth.authz`, `radd.modules.projects.service`, and `radd.modules.events.service` inside its handlers. The docstring is honest ("imports nothing at module load; the CRUD handlers [do]"), but the kernel now has a hard runtime dependency on three specific modules — a plugin platform whose kernel cannot function without `auth`/`projects`/`events` has those three as kernel components in fact. Fix: define kernel-owned protocol sockets (`authz_provider`, `event_emitter`, `project_resolver`) that `auth`/`projects`/`events` register at boot (the `sockets.py` mechanism already exists); `kernel/entities.py` calls the socket, never the module.

**Minor — `server/src/radd/kernel/sockets.py:26–29`**
Socket docstrings name concrete features (`google_chat | email | slack`, `gitlab/forgejo/alertmanager`). Comments only — no import, no behavior — but the kernel should describe socket shapes, not enumerate the plugins expected to fill them. Fix: reword as generic examples.

**Clean**: `kernel/specs.py`, `kernel/registry.py`, `kernel/loader.py`, `kernel/plugin.py`, `kernel/capabilities.py` import nothing from `radd.modules` and encode no feature behavior. `radd/worker.py`, `radd/hooks.py`, `radd/schedule.py`, `radd/maintenance.py`, `radd/middleware.py` are pure mechanism.

---

## 2. Core-module inversions (a lower layer importing a higher one)

**Critical — `auth` imports six feature modules it predates and outranks.**
- `auth/authz.py:919` + `auth/router.py:313` — `from radd.modules.pages.models import PageSpace` (raw model import, try/except-ImportError feature detection).
- `auth/models.py:198` — `GlobalRoleGrant.space_id = ForeignKey("page_spaces.id")` (RADD-791): the core permission table hard-wires the wiki's schema. The inline comment documents the tradeoff, but it means `auth` cannot exist without `pages`' migration.
- `auth/router.py:128–139` — `/auth/me` nav-facts imports `timelogging.service` and `forms.portal` to compute area visibility.
- `auth/router.py:284` — `access.inspect`; `auth/roles_router.py:158–170` — `groups.service`, `teams.service`, and **`teams.models.ProjectTeam` (raw model)**; `auth/grants.py:290` — `pages.spaces`.

`auth` is the module everything else may depend on; every one of these makes it depend back, so nothing can be unloaded and load-order comments ("deferred: teams loads after auth") paper over real cycles. Fix: this is the classic *aggregation inversion* — the features should contribute, auth should host. A kernel registry (`nav_fact_provider`, `permission_scope_provider`, `subject_provider`) each feature registers into; `space_id` becomes the polymorphic `(scope_type, scope_id)` that RADD-791 rejected, or a `scope` ResourceSpec contributed by `pages` through the access framework it already owns adopters for.

**Major — `events/router.py:10–11`** imports `auth.authz` + `auth.deps` while `auth` declares `depends_on=("events", "projects")` — a declared cycle at the base of the stack (`events` declares no dependency on `auth` at all). Fix: either bless `auth.authz`/`auth.deps` as spine (see Systemic), or move request-auth for the events feed behind a kernel dependency-injection seam.

**Major — `groups/service.py:297,328` ↔ `teams/service.py:13`**: `groups` defer-imports `teams.service` while `teams` imports `groups.models.Group` (raw model, `teams/models.py` also FKs `groups`). A two-module cycle with a model reach in one direction. Fix: `teams` (higher layer) may call `groups.service`; the reverse reaction in `groups` should be an event (`group.members_changed`) consumed by `teams`.

**Major — `cycles/router.py:101–105`, `cycles/service.py:318`**: `cycles` (loads before `items`) defer-imports `items.service`, `timelogging.duration`, `timelogging.timesheet` — none declared, two of them non-service internals. Fix: the cycle report is reporting's or timelogging's to compose; or declare the dependency and route through `timelogging.service`.

**Major — `teams/service.py:109`** defer-imports `items.service` (teams loads before items; undeclared). Same shape. **`linktypes/service.py:69`** defer-imports `items.models.ItemLink` (raw model, reverse of load order, undeclared). Fix for linktypes: items owns `item_links` rows; deleting/validating them on link-type delete belongs behind an `items.service` function or an in-transaction hook the `hooks.py` registry already supports.

**Minor — `projects/*`** imports `auth` and `settings` while declaring only `events`; `labels`, `webhooks` import `auth.authz`/`auth.deps` undeclared. Mechanical `depends_on` fixes.

---

## 3. Cross-module `models.py` imports (non-spine) — 78 sites

### 3a. The SLQ builtin catalog — items reaches into five modules' tables

**Major — `items/slq/builtins.py:12–16`** imports `cycles.models.{Cycle,ItemCycleRecord}`, `releases.models.Release`, `itemtypes.models.IssueType`, `teams.models.Team`, `workflow.models.State`; also `items/slq/suggest_values.py:185` (`IssueType`), `items/slq/ancestors.py:33` (`State`). Spec 97 built `SlqFieldSpec` precisely so "items never learns those modules exist", then left the builtin catalog hardcoded — `logged_by`/`commented_by` go through the registry while `cycle`/`release`/`type`/`team`/`state` do not. Fix: move each relational builtin into the owning module's `SlqFieldSpec` contribution (cycles contributes `cycle`, releases `release`, itemtypes `type`, teams `team`, workflow `state`/`status`). The registry's `item_ids` context already carries what these compilers need.

### 3b. items ↔ workflow / fields — the undeclared inner spine

**Major (as a class)** — `items` imports `workflow.models.State` in six files (`items/rollup.py:20`, `items/service/core.py:20`, `items/service/queries.py:14`, `items/service/relations.py:22`, `items/slq/ancestors.py:33`, `items/slq/builtins.py:16`) and `fields.models.FieldDefinition` in nine (`items/filters.py:20`, `items/listing.py:15`, `items/service/listing.py:13`, `items/service/read.py:16`, `items/service/visibility.py:17`, `items/slq/compiler.py:21`, `items/slq/custom.py:13`, `items/slq/helpers.py:14`, `items/slq/suggest.py:21`). Meanwhile **workflow imports items back**: `workflow/transitions.py:458` (`items.models.ItemLabel`, querying the items-owned join table), `:198` (`items.enums`), `transitions_router.py:76` (`items.service`), plus defer-imports of `comments`, `timelogging`, `fields`, `approvals` services at `transitions.py:467–488`. items↔workflow is a genuine cycle; `WorkItem.state_id` FKs `states` and every item query joins it. Fix: promote `workflow.models.State` (and plausibly `fields.FieldDefinition`) to declared spine, or export a query-fragment seam (`workflow.service.state_join()`/`category_filter()`); break the reverse edge by making the transition-guard snapshot a contribution: guards that need labels/comments/estimates/approvals are exactly the `SlqFieldSpec` shape — a kernel `guard_fact_provider` registry each module fills (approvals already ships the try/except version of this at `transitions.py:488`).

### 3c. Event consumers importing `events.models.Event` — 13 sites

**Minor (as a class), one-line fix** — `ai/embeddings/embedder.py:29`, `attachments/gc.py:20`, `automations/engine.py:35`, `csat/sender.py:31`, `googlechat/consumer.py:20`, `items/history.py:19`, `mailintake/outbound.py:30`, `notify/consumer.py:23`, `realtime/broadcaster.py:14`, `realtime/hub.py:15`, `reporting/timeline.py:28`, `search/indexer.py:23`, `webhooks/service.py:17`. The `Event` row **is** the consumer contract; the violation is only that the contract type lives in `models.py`. Fix: re-export `Event` from `events/service.py` (or `events/__init__.py`) as the declared payload type and update the 13 imports; forbid `events.models` after that.

### 3d. Feature modules importing `items.models.WorkItem` — ~20 sites

**Major (as a class)** — `ai/service.py:400`, `automations/email_action.py:19`, `automations/engine.py:40`, `canned/service.py:10`, `csat/report.py:16`, `csat/sender.py:34`, `forms/requests.py:48`, `jiraimport/rollback.py:26`, `notify/consumer.py:26`, `participants/__init__.py:7`, `participants/service.py:32`, `releases/pipeline.py:21`, `search/deflect.py:18`, `slas/report.py:17`, `slas/service.py:19`, `timelogging/slq/compiler.py:24`, `timelogging/timesheet.py:21`, `views/counts.py:21`, `workflow/transitions.py:458`. Most exist to run one aggregate/join the `items.service` API doesn't offer (counts by state, titles for digests, `IN (SELECT id …)` wrappers). Fix: either bless `work_items` as spine (it has 14 FK dependents — see §5) with a documented read-only rule, or add the handful of missing `items.service` query functions (`item_ids_matching(filters)`, `titles_for(ids)`, `counts_by(project, group)`) and route these through them. The first option matches reality; the second preserves the letter of rule 1. Recommended: extend the spine (see Systemic fixes).

### 3e. Access-framework adopters importing `AccessGrant` directly

**Major** — `dashboards/service.py:20`, `fields/service.py:11`, `views/service.py:12`, `pluginmgr/service.py:248` import `access.models.AccessGrant` although the access module was built as the one generic ACL primitive with a public resolution seam (`access/resolution.py`, `access.registry`, `access.inspect` — which other callers correctly use). Adopters querying the grants table directly re-create the pre-spec-92 world where every module hand-rolled ACL SQL. Fix: add the missing read functions to `access.resolution`/`access.service` (e.g. `grants_for_resource`, `subject_filter(resource_type)` returning a composable SQLAlchemy fragment) and drop the model import; `access` already registers `ResourceSpec`s for exactly these four adopters.

### 3f. Remaining raw model imports

- **Major** `forms/requests.py:46,48,51,214` + `forms/staging.py:42` — `comments.models.Comment`, `items.models.WorkItem`, `workflow.models.State`, `releases.models.Release`, `attachments.models.Attachment`: the requester-portal composes five modules' tables directly. Fix: portal read models via each module's service (comments and attachments both have list functions already).
- **Major** `notify/consumer.py:20` — `comments.visibility.internal_comment_visible`, a comments-internal helper, plus `comments.types` at :19. The visibility decision belongs to comments: export it from `comments/service.py`.
- **Major** `ldap/groupsync.py:32,139` — `groups.models.{Group,GroupMember}`: the directory sync writes another module's tables. Fix: `groups.service.upsert_group/replace_members` (merge/repoint semantics live with the owner).
- **Major** `search/semantic.py:94` — `pages.models.Page`; pages is optional and search is supposed to reach it via `pages.search`/`rows_for_embedding` seams (which `ai` uses). Fix: same seam.
- **Minor** `pages/labels.py:22` — `labels.models.Label` (plus `pages/models.py` FK to `labels`): pages reuses tracker labels. `labels.service` is already imported on the line above; add `labels.service.by_ids` and drop the model import.
- **Minor** `ai/nlrepair.py:25,194` + `ai/service.py:23` — `fields.models.FieldDefinition`, `timelogging.models.WorkCategory` for prompt vocabulary. Both owners have service functions listing these; use them.
- **Minor** `approvals/service.py:38` — `workflow.models.WorkflowTransition`; approvals already declares `workflow`: export a `transitions_for_state` service function.
- **Minor** `access/service.py:235` — `auth.models.GlobalRoleGrant` and `pages/access.py:26` — `auth.models.Role`: the spine exception covers `User` only. Export role lookups from `auth.roles`/`auth.service`.
- **Minor** `attachments/routing/rules.py:114–116`, `engine.py:77` — `ai.client`/`ai.features`/`ai.types` from a module that loads before `ai`, feature-detected. `ai/client.py` is the documented instance-wide seam, so this is contract-conformant in spirit; the load-order inversion should still be declared (an optional-dependency field on `RaddPlugin`, cf. §6).

---

## 4. Raw SQL crossing table ownership

**Major — `jiraimport/rollback.py:176–209`**: `_PROJECT_CHILDREN = ("views", "forms", "releases", "work_items", "issue_types", "states", "project_timelogging")` with `text(f"DELETE FROM {table} WHERE project_id = :id")`, plus `:196` `SELECT count(*) FROM work_items`. Seven modules' tables deleted by string name — invisible to grep-by-import, silently wrong the day any owner renames or adds a child table (a project-scoped table added later is *not* cleaned up and blocks the project delete). Fix: this is a "cascade delete a project" capability — a kernel-level `project_purge` hook each module registers (the in-transaction `hooks.py` registry fits), or `projects.service.hard_delete(project_id)` that dispatches it. The rollback module then deletes nothing it doesn't own.

**Major — `ai/embeddings/service.py:276–289`**: `SELECT count(*) FROM search_index` and `SELECT count(*) FROM pages WHERE archived_at IS NULL` — raw reads of `search`'s and `pages`' tables for the coverage endpoint, while the text itself correctly flows through `search.rows_for_embedding`/`pages_for_embedding`. Fix: add `count`/`corpus_size` to those same two seams.

**Minor (documented) — `search/indexer.py:169–214`**: `_RESTORE_OPEN`/`_RELATION_SYNC` update `search_index` FROM `work_items` in raw SQL. The file itself cites "the timesheet's tolerated inward read of dependency tables" precedent. Acceptable as a declared exception, but the exception exists nowhere but this comment — record it in `docs/modules.md` or convert to an `items.service` read.

**Cross-module FK census (38 references beyond users/projects)** — not individually actionable, but the fact base for the spine decision: `work_items` ← alertmanager, approvals, csat, cycles, jiraimport, mailintake, notify, pages, participants, search, slas, timelogging(×2), vcs, views, weblinks; `teams` ← auth, comments, cycles, forms, leave, participants, sso; `states`/`workflow_transitions` ← approvals, items; `labels` ← items, pages; `issue_types` ← items, screens; `groups` ← auth, teams; `roles` ← sso, teams; `page_spaces` ← auth. The kernel already has the mechanism for plugin-owned FKs (`kernel/specs.py:197`, `fk: "work_items.id" — cross-plugin FK (kernel-owned)`); core modules bypass it.

---

## 5. Registry bypasses and hardcoded module knowledge

**Critical (systemic) — `auth/types.py:35` `class Permission(StrEnum)` (~150 members)**: `item.*`, `comment.*`, `worklog.*`, `timesheet.*`, `page.*`, `form.*`, `cycle.*`, `sla.*`, `release.*`, `csat.*`, `cardpreset.*`, `vcsconn.*` … — every module's atoms centrally enumerated in auth, while the kernel permissions registry exists and `milestones` proves atoms can be contributed with zero auth edits. Two parallel systems: plugins contribute, core modules edit auth. Fix: modules declare their atoms on their `RaddPlugin` (most already have the `CRUD_RESOURCES` one-liner pattern); `Permission` becomes a kernel-validated string newtype resolved against the registry; `auth` keeps only `global.manage`/`project.manage`-class primitives.

**Major (systemic) — `settings/types.py:34` `class SettingKey(StrEnum)`**: `AI_*` (7), `CSAT_ENABLED`, `RELEASE_*` (2), `TIMESHEET_*`/`TIMELOG_*` (4), `LDAP_*` (12), `WORKFLOW_TRANSITION_MODE`, `ESTIMATION_POINTS` — the settings module knows every feature's tunables. The file calls itself a registry; it is a hardcoded enum. Fix: `RaddPlugin.settings: tuple[SettingSpec, ...]` contribution; the settings module keeps the cascade mechanism and validates keys against the kernel registry. (`docs/modules.md` row per contribution keeps rule 3 satisfied.)

**Major — MCP registry has one client.** `mcp/tools.py:17–40` imports ten modules to implement 19 hardcoded tools; `mcp/catalog.py:434–442` merges kernel `registries.mcp_tools` (used only by `milestones/mcptool.py`); `mcp/pages_bridge.py` special-cases the pages module by import path (`PAGES_MODULE_PATH`) with `importlib` + `inspect` signature-matching — a hand-written duck-typing bridge where a `McpToolSpec` contribution from `pages` would be nine declarative lines. Fix: migrate the core tools into their owning modules' `McpToolSpec` contributions (items tools to items, worklog tools to timelogging, release tools to releases, page tools to pages — deleting `pages_bridge.py`); the mcp module keeps protocol + dispatcher only. This also fixes the catalog/enforcement drift class RADD-674 audited, permanently.

**Major — `seed.py:18–23`**: imports `auth.models`, `auth.security`, `auth.schemas`, `auth.types`, **and `timelogging.categories`** — the bootstrap seeder special-cases one feature module by name (default work categories). Every other module seeds its defaults via project-created hooks. Fix: a `seed` lifecycle hook on `RaddPlugin` (or reuse `on_startup` idempotent seeding, which several modules already do); `seed.py` keeps only the admin-user creation, for which the auth imports are legitimate.

**Minor — `app.py:28`**: `from radd.modules.pluginmgr.boot import resolve_boot_paths` — the app factory hardcodes one module to discover the rest. A bootstrap module is defensible, but the function reads `installed_plugins` by raw SQL (`pluginmgr/boot.py:29`, its own table — fine) and could live in the kernel loader with pluginmgr contributing the DB-backed source.

**Minor — `sdk.py:57–79`**: the extension-SDK facade is a hand-maintained dict of `("radd.modules.X.service", "fn")` pairs, including non-service paths (`auth.authz`, `auth.deps`, `auth.types`, `access.registry`). As the *public* SDK it will silently drift from the modules it names. Fix: modules contribute their SDK exports on `RaddPlugin` (an `sdk_exports` mapping) and `sdk.py` composes them.

**Minor — `automations/types.py::SYSTEM_ACTOR_ID`** imported by `releases/pipeline.py:20` (and others): the system actor is an instance-wide identity fact, not an automations concept, and it drags an undeclared automations dependency into releases. Move to `auth` or the kernel.

**Minor — generic machinery living inside modules**: `events/runner.py` (imported by 5 modules) and the `items.slq` lexer/parser/helpers (imported by `timelogging`, `ai`, `mcp` — 15+ sites, e.g. `timelogging/slq/compiler.py`, `ai/service.py:623`). Both are acknowledged in CLAUDE.md as kernel-bound ("they belong in the kernel eventually; don't copy them"). Findings only because every importing module must currently declare a dependency on `events`/`items` for what is really kernel code. Fix: move to `radd/kernel/` (query machinery) and `radd/worker.py` (runner) on the next touch.

---

## 6. `depends_on` drift (declared vs. imported)

**Major (as a class)** — 30 modules import undeclared dependencies; the loader's ordering guarantees are only as good as these declarations. Full table (undeclared = imported but not declared; unused = declared but never imported):

| module | undeclared imports | unused declarations |
|---|---|---|
| access | groups | — |
| ai | events, pages, timelogging | — |
| attachments | access, ai, groups, teams | — |
| audit | — | projects |
| auth | **access, forms, groups, pages, teams, timelogging** | — |
| automations | fields, mailintake, notify | labels |
| csat | workflow | — |
| cycles | **items**, settings, teams, timelogging | projects |
| dashboards | access, groups | — |
| events | **auth** | — |
| fields | — | teams |
| forgejo | releases | — |
| forms | attachments, automations, comments, itemtypes | labels |
| gitlab / googlechat / ldap / sso / labels / webhooks | (sso: teams; labels/webhooks/events: auth) | projects (several), auth (googlechat) |
| groups | **teams** | — |
| items | access, **approvals**, **comments**, itemtypes, **linktypes**, **timelogging** | — |
| jiraimport | events, itemtypes, linktypes, notify, releases, timelogging, weblinks | — |
| linktypes | **items** | — |
| mcp | cycles, itemtypes, linktypes, releases, search, timelogging | — |
| milestones | — | auth, events |
| notify | participants, teams | — |
| pages | access, ai, groups, search, teams | — |
| pluginmgr | access | — |
| projects | auth, settings | — |
| releases | automations, **items**, settings, **workflow** | — |
| reporting | csat, slas | — |
| screens | — | itemtypes |
| search | access, ai, fields, pages, teams | — |
| teams | access, **items** | — |
| timelogging | settings | — |
| views | groups, teams | — |
| workflow | approvals, comments, fields, **items**, teams, timelogging | — |

Bolded entries are **cycles** (each side imports the other): items↔workflow, items↔linktypes, items↔timelogging, items↔comments, items↔approvals, groups↔teams, auth↔events, releases↔items/workflow (releases loads before both). Several files carry `# deferred: X loads after Y` comments — the honest symptom. `reporting/__init__.py:13` even documents one edge as "undeclarable in depends_on without a load-order cycle". Fix: (a) add an `optional_after`/`weak_depends` field to `RaddPlugin` so feature-detected reverse edges are *declared* rather than commented; (b) a test that walks module ASTs and asserts every `radd.modules.X` import is declared (the route-shadowing test is precedent for this kind of whole-app assertion); (c) break the bold cycles via the registries in §3b/§2.

**Minor** — the ~296 `.types`/`.enums`/`.schemas`/`.deps` imports (auth.deps 56, auth.types 34, items.enums 23, workflow.types 20, items.schemas 18, fields.types 17, settings.types 14, …) are a gray zone the contract doesn't mention: types are the least-coupling import there is, but nothing marks which are public. Fix: declare types/enums/schemas public alongside `service.py` in the contract (CLAUDE.md rule 1) rather than churn 300 imports.

---

## 7. Frontend

**Clean — the plugin half.** `web/src/lib/plugin-loader.ts` is fully generic (diff-load remotes, version-gate, quarantine, live unregister); `router.tsx:214` uses a catch-all `$` route for plugin pages; no plugin is named anywhere in host code (the two "milestone" hits are comments); remotes are colocated per-plugin (`<plugin>/ui/`) and discovered by `web/scripts/build-all.mjs`, importing only `@radd/plugin-sdk`. Slot sites (`IssueProperties.tsx:325,347`, `item-detail.tsx:305`, `view.tsx:953,1102`, `profile.tsx:108`, `settings/plugins.tsx:125`) match the spec-94 registry.

**Minor — builtin view types are enum-special-cased beside a working registry.** `routes/view.tsx:243,417–418,601–606,775,1143`, `components/shell/SidebarRows.tsx:172–176`, `Sidebar.tsx:106`, `lib/columns.ts:134–135`, `ViewModal.tsx:112–118` branch on `ViewType.board/planning/queue/roadmap` by name, while `view.tsx:1102` already renders `<Slot id={SlotId.viewType} match={view.view_type}>` for plugin types. Two-tier by design (the host owns its builtins), not a violation — but registering the builtin renderers into the same slot registry would delete the branches and make builtins the reference implementation for plugin authors. Same shape for dashboard widgets (`WidgetModal.tsx:40–48` hardcodes nine builtin widget types; plugin widgets come via the registry).

**No cross-plugin frontend reaches found**: no remote imports another remote or host internals; shared state flows through `globalThis.__RADD_SHARED__` singletons as designed.

---

## 8. Module loader coverage

All 53 directories under `server/src/radd/modules/` expose `plugin = RaddPlugin(...)` in `__init__.py`; `config.py:322–380` assembles 52 in `Settings.modules` plus `milestones` in `installable_plugins`; `app.py` loads exclusively through `import_models`/`load_plugins`. **No module bypasses the loader.** (The `radd/backup/` root package is shared pg_dump machinery used by the `backup` module — mechanism, not an unregistered module.)

---

## Systemic fixes

1. **Re-declare the spine to match reality, then enforce it.** The written exception (User, Project) is fiction: `work_items`, `teams`, `workflow.State`, `auth.Role`, `labels`, `groups`, and the `events.Event` payload are load-bearing for 8–20 modules each. Decide the real spine set (recommended: add `WorkItem` read-only, `State`, `Team`, `Event`; keep everything else off-limits), write it into CLAUDE.md rule 1, and add a CI test that AST-walks `radd.modules` and fails on any `X.models` import outside the blessed set. That one test converts §3's 78 findings from audit prose into a ratchet — fix the list to green once, and the class is closed forever.

2. **Same test, second assertion: imports ⊆ depends_on.** Every `from radd.modules.X` in module Y must appear in Y's `depends_on` (or a new `weak_depends` for feature-detected reverse edges). This surfaces every future cycle at commit time instead of as a `# deferred: loads after` comment.

3. **Finish the registry migrations the kernel already shipped.** Four registries exist with exactly one client each while the core stays hardcoded: SLQ relational fields (§3a — move `cycle`/`release`/`type`/`team`/`state` builtins into owner `SlqFieldSpec`s), MCP tools (§5 — move all 19 core tools + delete `pages_bridge.py`), permissions (§5 — atoms on `RaddPlugin`, kill the central enum), settings keys (§5 — `SettingSpec` contributions). Each migration deletes a central catalog *and* its special-case bridge, and `milestones` is already the proven template for all four.

4. **Invert auth's feature knowledge with one aggregation registry.** Nav-facts, permission-scope labels, and inspector subjects are three instances of "auth composes an answer from feature-owned facts". One kernel `fact_provider` socket (feature registers, auth iterates) removes every `auth → pages/forms/timelogging/teams/groups` import in §2 and keeps the next feature from editing auth at all.

5. **Kernel sockets for the kernel's own runtime needs.** `kernel/entities.py` calling `auth`/`projects`/`events` through registered providers (§1) is the same pattern as #4 applied one layer down; it makes the kernel honest and gives the entity factory a test seam.

6. **Project lifecycle hooks instead of table lists.** `jiraimport/rollback.py::_PROJECT_CHILDREN` is the only place in the codebase that enumerates "what hangs off a project" — a `project_purge` hook each module registers (via the existing `hooks.py` registry) makes project deletion complete by construction and removes the raw cross-module SQL.

7. **Relocate the acknowledged kernel-bound machinery** (`items.slq` lexer/parser/helpers, `events/runner.py`, `SYSTEM_ACTOR_ID`) on next touch — each move deletes a false dependency edge from every current importer, which is the cheapest way to shrink the §6 table.
