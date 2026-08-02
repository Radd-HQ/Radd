# Spec 93 — Kernel + Plugin Platform (the migration)

**Status:** in progress. This spec is the **definition of done** for migrating Radd
onto the kernel+plugin architecture (`docs/plugin-platform.md`). It is a checklist: every
architecture deliverable and every existing capability (specs 01–92) that must still hold. Nothing
is dropped silently — an unchecked box at the end is an explicitly-logged parity gap (`BUILD-LOG.md`).

Convention: `[ ]` todo · `[x]` done + verified green · `[~]` partial/scaffolded (see BUILD-LOG).

---

## Part A — Architecture deliverables (the kernel/plugin machinery)

### A0. Kernel package + plugin contract
- [x] `radd/kernel/` package holds the generic machinery (loader/lifecycle, registries, entity
      registry, event-type registry, access/permission/crud registries, settings, capabilities,
      sockets, sdk surface). Kernel is never disabled. *(registries + loader shipped; entity/sdk
      registries fleshed out in later slices)*
- [x] `RaddPlugin` manifest (evolves `RaddModule`): identity (`id`, `version`, `api_version`,
      `core`, `depends_on`), + contribution fields (`entities`, `routers`, `event_types`,
      `consumers`, `automation_actions/conditions`, `tasks`, `settings_keys`, `settings_sections`,
      `permissions`, `crud_resources`, `access_resources`, `capabilities`, `integrations`, `ui`,
      lifecycle hooks). All new fields optional/defaulted.
- [x] Loader aggregates each contribution field into a kernel registry; every existing module loads
      as a `core: true` plugin with empty new fields — **zero behavior change** (920 tests green).
- [x] `RaddModule` kept as a back-compat alias so unconverted modules keep loading during migration.

### A1. Invert the three backwards dependencies (§3)
- [x] **Chokepoint 1 — automation triggers:** `automations/catalog.py` no longer imports 21 modules'
      enums; `TRIGGERS` is derived from the kernel **event-type registry**. Each producer registers
      its event types (label/group/item_scoped/has_changes) via its manifest `event_types=`. Entity
      CRUD events auto-registered (later). *Parity oracle: `tests/test_trigger_registry.py` pins the
      65-trigger catalog exactly; 929 tests green.*
- [x] **Chokepoint 2 — capabilities:** a `/capabilities` aggregator endpoint (new `capabilities`
      core plugin + `kernel/capabilities.py`) evaluates every registered `CapabilitySpec`. 12
      descriptors contributed by their owning plugins (sso/ldap/ai/storage/mfa/smtp/workers + 5
      connectors). `/instance/status` + `/instance` + `/instance/login-options` reimplemented to
      consume the registry (connectors derived generically from `category=='connector'`), removing
      the inlined `bool(settings.*)` logic. *Parity: `tests/test_capabilities.py` asserts each check
      reproduces the old inline expression; 933 green.* (`/ai/status` left as-is — separate surface.)
- [ ] **Chokepoint 3 — frontend nav:** the SPA renders nav / settings-nav / routes from a
      backend-assembled UI manifest (gated by `/auth/me` atoms) instead of hand-authored arrays.

### A2. RBAC registries become plugin-contributable (§7)
- [x] **Permission atoms** — a plugin declares `permissions=(PermissionSpec…)` in its manifest;
      `kernel.register_permission` also exposes it. Merged-view accessors in `auth/types.py`
      (`all_permission_keys`/`permission_scope_of`/`permission_description_of`) fold registered atoms
      in LIVE alongside the builtin enum. Atoms flow as **strings** through the union engine
      (`authz.combine_permissions` no longer coerces to the enum), so a plugin atom is grantable +
      admin holds it. `GET /permissions` lists builtins (enum order) then plugin atoms.
- [x] **CRUD resources** — `crud_resources=(CrudResourceSpec…)` / `kernel.register_crud_resource`;
      `implied_map()` merges the plugin `manage`→atoms closure with the builtin `IMPLIED_PERMISSIONS`.
      *Parity: default config has an empty registry, so every accessor == the builtin set exactly
      (`tests/test_rbac_registry.py::test_no_registered_plugin_means_builtins_only`); 939 green.*
- [x] **Access grants** already dynamic (`access.registry.register_resource`) — fields/builtin_field/
      view register via it; a plugin registers a `ResourceSpec` the same way.

### A3. `kernel.entities` auto-wiring (§0.5)
- [x] `EntitySpec` declarative registration (`kernel/entities.py`) → generated SQLAlchemy model
      (imperative Table mapping from a field DSL; `model=` escape hatch) + auto-registered
      `created/updated/deleted` event types (→ automations/webhooks/audit) + `create/update/delete`
      CRUD-resource RBAC atoms + a generic permission-guarded CRUD router (mounted by app.py) +
      `ensure_tables()` install step. The loader auto-wires on `plugin.entities`.
- [~] activity/search/mention/link + access `ResourceSpec` auto-wiring: events flow to
      audit/webhooks/automations already (auto). **Search** is the one north-star surface not yet
      lit for a generic entity — the search index (`SearchIndexRow`) is `item_id`-keyed and the Cmd-K
      palette renders item hits, so indexing an arbitrary entity is a coordinated backend
      (generalize the index schema + indexer) **and** frontend (palette rendering) refactor. The
      `EntitySpec.searchable`/`mentionable` seams are declared; wiring them is the bounded follow-up
      (deliberately not undertaken here to avoid destabilizing the 961-green baseline for one of four
      north-star surfaces already delivered). Logged.

### A4. Lifecycle & plugin manager (§10)
- [x] `installed_plugins` table (id, version, state, config) — source of truth (migration
      `e53d08a57e29`). `pluginmgr` core plugin.
- [x] States: DISCOVERED → INSTALLED → ENABLED ⇄ DISABLED → UNINSTALLED (`pluginmgr/types.py` +
      `service.py` state machine). Enable/disable flip state + hot-mount/unmount routers in the
      running app (`runtime.py`, popping the SPA catch-all so new routes precede it); `create_app`
      resolves the ENABLED set at boot (`boot.py`, sync read). Install/uninstall are the heavy steps.
- [x] Plugin-manager service + admin API (`GET /plugins`, `POST /plugins/{id}/{install,enable,
      disable,uninstall}`, instance-admin) can enable/disable each plugin; core plugins locked
      (`can_toggle=False`, disable → 409). `tests/test_plugin_manager.py` (7). Smoke: enable
      milestones → `/api/v1/milestones` mounts; disable → unmounts.
- [x] **Admin UI**: `Settings → Plugins` (`web/src/routes/settings/plugins.tsx`) — lists every
      plugin with its state badge; core rows show a lock, non-core get Enable/Disable buttons that
      call the API and invalidate the capabilities manifest (so the sidebar plugin-nav updates live).
      In `SETTINGS_NAV` (instance-admin) + the router. Frontend builds clean.
- [~] Failure isolation (errored quarantine) — `PluginState.ERRORED` defined; loader still fails
      hard on a bad core plugin. Non-core hot-mount failures are swallowed (state still flips). Full
      boot-survives-a-bad-plugin quarantine logged as a follow-up.
- [~] Per-plugin migration: entity tables are in the main alembic chain today (installable-plugin
      models scanned by env.py so autogenerate doesn't drop them). Per-plugin branch labels (§5) not
      yet — logged. Admin UI = a declarative surface via the nav/capabilities manifest (A7).

### A5. Public SDK + versioning (§9)
- [x] `radd/sdk.py` re-exports the public surface: the kernel contract + specs + `register_*` fns +
      `Base`/session (eager), and the acting-user-scoped data SDK (items/comments/projects/perms/
      settings/events/access) lazily via PEP 562. The north-star `milestones` plugin imports ONLY
      from `radd.sdk`. `tests/test_sdk.py` (4).
- [x] `api_version` semver gate: `kernel.loader._api_compatible` + `load_plugins` refuses a plugin
      whose api_version major mismatches the kernel — proven end-to-end
      (`test_sdk.py::test_loader_refuses_incompatible_api_version`).

### A6. Permission-aware data SDK (§7.5)
- [x] The acting-user-scoped data services (`items.get_item/list_items/create_item/update_item`,
      `comments.list/create`, `projects`, `authz.effective_permissions/require`, `settings.resolve`)
      are re-exported through `radd.sdk` (A5) — every one takes the acting `User` and enforces row +
      field-level grants by construction (§7.5), so a plugin gets permission-scoped data with no auth
      code. (`list_items(actor, filters, q)` is the SLQ query surface.)
- [~] A dedicated `kernel.as_system(reason=…)` audited-escalation wrapper is not yet a named helper —
      system callers pass a system actor today. Logged as a naming/formalization follow-up.

### A7. Frontend platform (§8)
- [x] `/capabilities` UI-manifest (8a) carries `capabilities` + plugin `nav`; the SPA sidebar
      renders plugin-contributed nav items from it (`capabilitiesQuery` → `Sidebar` `pluginNav`,
      gated by `requires` atoms + enabled capability), so an enabled plugin's nav appears with no
      edit to the shell (chokepoint 3). Frontend builds clean (tsc + vite). Additive — the builtin
      hardcoded nav is untouched (no regression).
- [~] Full replacement of the hardcoded `SETTINGS_NAV` / router tree by the manifest (8a-complete) is
      a follow-up — the additive plugin-nav proves the seam; ripping out the working builtin arrays
      is deferred (parity risk, no visual test harness here). Logged.
- [ ] Declarative UI manifest vocabulary (8b-B) for CRUD-shaped plugin pages + generic plugin route.
- [ ] Module-federation remote loading (8b-A) for bespoke plugin UI (host singletons). Deferred (§8b
      is the doc's "later"; needs a Vite module-federation host).

### A8. Sockets & primitives (§4a, §6, §13)
- [x] `kernel/sockets.py` — socket registry (over `registries.integrations`) + Protocol interfaces;
      `providers`/`provider`/`active_provider` resolve by name/settings. `tests/test_sockets.py`.
- [x] `TaskBackend` socket: `capabilities` registers the `localloop` default
      (`worker.LocalLoopBackend` over `PeriodicLoop`); a celery plugin swaps it. Consumer migration
      from hand-rolled loops to `schedule()` is incremental (logged).
- [x] `StorageBackend` socket: `attachments` registers `filesystem` + `s3` providers (thin adapters
      over `storage.py`); active one resolves from `attachment_storage`.
- [~] `AttachmentFilter` + `Notifier` interfaces defined ([seam] — no second provider yet). Connector/
      AIProvider/VcsProvider stay their module interfaces; formalizing as socket providers is
      incremental. §13 primitives (credential vault/OAuth, interceptor registry, egress policy,
      bot-actor, portal-context, field-type registry) are designed-not-built — not yet stubbed. Logged.

### A9. Per-plugin dependencies (§14)
- [x] `RaddPlugin.python_deps` / `js_deps` — each plugin declares its own deps in its manifest
      (e.g. `ldap` → `ldap3`, `attachments` → `minio`); the manifest is the single source of truth
      the install step resolves. `tests/test_kernel.py::test_plugins_declare_their_own_dependencies`.
- [~] Restructuring `pyproject` so builtins are real optional-dependency extras (`radd[ldap,s3,…]`)
      with a lean default install requires making feature modules conditionally importable — deferred
      (orthogonal packaging change; declarations are in place for the install step to consume).
      Frontend module-federation remotes = the §8b-A follow-up.

### A10. North-star acceptance (§1)
- [x] A `milestones/` plugin (`radd/modules/milestones/` — one `EntitySpec` + a nav item) lights up:
      auto-generated table + CRUD endpoints (`/api/v1/milestones`), `milestone.created/updated/deleted`
      events (⇒ automation triggers + webhooks + audit), `milestone.create/update/delete` RBAC atoms
      (in the roles matrix), and a nav item — **with zero edits to any other plugin or the kernel.**
      Proven by `tests/test_north_star.py` (6 tests: trigger, RBAC, nav, entity/CRUD, disableable,
      real DB round-trip). `core=False` — installed (migration `a29615cf474d`), runtime-enabled via
      the plugin manager (A4). *(search/mention wiring: see A3 [~].)*

---

## Part B — Feature parity inventory (specs 01–92): every module still works

Each module is reclassified as a `RaddPlugin` and its behavior preserved (tests green). Grouped by
the assembly order in `config.settings.modules`.

**Status (collective):** ALL modules below load as `core: true` plugins with the additive manifest
fields and **zero behavior change** — proven by `test_kernel.py` (every plugin loads, all core) + the
full **961-test suite green on a fresh seeded DB**, which is the per-module parity oracle. The
reclassification is the doc's §11 path (additive fields, not a rewrite), so every spec-01–92
capability is preserved by construction. The boxes below are therefore satisfied as a set; only
capabilities called out with a `[~]` in Part A (generic-entity search/mention, full 8b frontend,
per-plugin alembic branches, §13 primitives) remain as logged follow-ups.

### Kernel-provided (generic mechanism → kernel; some split from a plugin)
- [ ] `events` — transactional outbox + audit log + event-type registry (`emit`, `GET /events`,
      `query_events`, `entity_activity`, `runner.run_head_seeded`). *kernel*
- [ ] `auth` (split) — kernel keeps identity/sessions/permission-atom registry/RBAC/access/security
      context; login methods (local) stay. Users, sessions, PATs, roles-as-data (06), CRUD atoms
      (50), global grants (87), scopeable grants (91), user admin (84), hard-delete+reassign (89),
      duplicates/merge (84/88). `GET /auth/me`, `/permissions`, `/roles`, `/role-grants`.
- [ ] `settings` (split) — kernel keeps the scalar cascade platform; keys owned per plugin. Two-scope
      cascade, `SettingKey`/`SettingSpec` registry, `/scoped-settings[/resolve]`, directory keys (85).
- [ ] `access` — generic scopeable access-grant framework (92): `access_grants`, `register_resource`,
      `/grants`, resolution. Adopters: fields, builtin_field, view.

### Tracker core plugins
- [ ] `projects` — projects as global containers, globally-unique keys (86), `GET /instance[/status]`.
- [ ] `teams` — teams + membership + project role attach (86), directory teams (84/87), delegation
      (owner/managers, 87).
- [ ] `workflow` — per-project states, transitions + guards (61), transition modes, `state.delete` (87).
- [ ] `labels` — global labels, auto-create, rename/recolor/delete (87).
- [ ] `fields` — custom field registry, validation, defaults (50), multi-project scope (90/91),
      grants via access (92).
- [ ] `cycles` — cross-project iterations (14/60/23/56), sprint close, recurring series, cadence,
      stats+points (70), team visibility.
- [ ] `releases` — project releases/versions.
- [ ] `itemtypes` — per-project issue types (51) + colored chips + templates (76).
- [ ] `screens` — field-layout config (53).
- [ ] `linktypes` — user-definable scopeable link types (91).
- [ ] `items` (split) — kernel keeps entity+link+SLQ machinery; the issue (epic/issue/subtask,
      fields, boards, ranking, bulk 68, mentions 52, archive/delete 38) stays a plugin.
- [ ] `comments` — comments, internal/team visibility (50).
- [ ] `weblinks` — web links on items.
- [ ] `vcs` — VCS refs on items.
- [ ] `views` — saved views + SLQ + swimlanes; view sharing via access (92).
- [ ] `reporting` — reports/charts.
- [ ] `forms` — intake forms (17), public tokened forms (62).
- [ ] `automations` — triggers (any-event, 58) + conditions + universal actions, scheduled rules (69),
      transition guards, send_email/canned vars (66).
- [ ] `timelogging` — estimates, worklogs, categories, timesheets (22/35), itemless worklogs (60),
      points (70).
- [ ] `audit` — admin audit query over the event log.
- [ ] `notify` — notifications + watchers + inbox (26) + email digests.
- [ ] `realtime` — WS live updates (27).
- [ ] `search` — FTS + Cmd-K palette (28).
- [ ] `attachments` — attachments (29) + storage backends filesystem/S3 (33).
- [ ] `canned` — canned responses (30).
- [ ] `slas` — SLA policies, business hours, priority first-match, reports, due-soon (30/35/61-67/69).
- [ ] `dashboards` — dashboards + sharing (75/57).
- [ ] `docs` — wiki: spaces/page-trees/versions/issue-links + FTS (43).
- [ ] `approvals` — transition approvals (71).
- [ ] `participants` — request participants (72).

### Integration / connector / auth-method plugins
- [ ] `sso` — OIDC SSO + group→role sync (40). *auth-method*
- [ ] `ldap` — LDAP/AD bind + directory sync + AD import + duplicates (42/49/84/85/87/88). *auth-method*
- [ ] `gitlab` — GitLab connector (31). *connector*
- [ ] `forgejo` — Forgejo/Gitea connector (47). *connector*
- [ ] `googlechat` — Google Chat notifier (47). *notifier*
- [ ] `alertmanager` — Alertmanager intake (47). *connector*
- [ ] `mailintake` — email-to-issue + requester loop (47/62). *connector*
- [ ] `csat` — CSAT surveys (65).
- [ ] `ai` — AI summarize/similar/NL→SLQ, provider-agnostic (46). *AIProvider socket*
- [ ] `mcp` — embedded MCP server (45).
- [ ] `jiraimport` — live Jira import wizard (90) + editable mappings/upsert follow-ups.
- [ ] MFA / TOTP (48), packaging (Containerfile/compose/Helm, 48).
- [ ] External-extension tier preserved: `sdk/` runner over `GET /events` + `POST /api/v1/mcp`.

---

## Verification gates (all must hold for DONE)
- [x] `alembic upgrade head` clean (live `radd` + fresh `radd_test` both at head `e53d08a57e29`);
      `create_app()` boots (210 API paths); `web/dist` built (tsc + vite clean).
- [x] Full `pytest` green — **961** on a fresh seeded DB, extended with kernel core-invariant tests:
      loader/registries (`test_kernel`), event-type registry (`test_trigger_registry`), RBAC registry
      (`test_rbac_registry`), capabilities (`test_capabilities`), entities/north-star
      (`test_north_star`), lifecycle (`test_plugin_manager`), SDK/api_version (`test_sdk`), sockets
      (`test_sockets`).
- [~] Demo scripts: **broken on `main` too** — `demo.sh` (and siblings) predate spec 86 and POST the
      removed `/workspaces` surface (the script says so at its top). Not a migration regression; the
      961-test fresh-DB suite is the stronger equivalent oracle. Updating the demos to the global
      surface is an orthogonal follow-up. Logged in BUILD-LOG.
- [x] UI: no regressions — every backend endpoint the SPA calls is preserved (parity tests for
      `/instance/status`, `/auth/me`, `/permissions`, `/roles`; wire shapes byte-identical). The SPA
      code is unchanged except the additive plugin-nav; `web/dist` rebuilds clean.
- [x] Plugin manager can enable/disable each plugin (core locked) — `test_plugin_manager` +
      live smoke (enable milestones → `/api/v1/milestones` mounts; disable → unmounts).
- [x] North-star `milestones` plugin (A10) passes with zero edits elsewhere (`test_north_star`).
