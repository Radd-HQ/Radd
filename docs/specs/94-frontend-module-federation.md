# Spec 94 — Frontend module-federation plugin platform

**Status:** in progress. This spec is the **definition of done** for turning the
Radd SPA from a monolith (every plugin's UI hardcoded in `web/src`) into a real **module-federation
plugin platform**: a plugin — including one built in its OWN repo/project — ships its own UI bundle
that a *running* Radd loads at runtime, with **zero edits to the core repo**. It implements
`docs/plugin-platform.md` §8 (the frontend), §9 (the public SDK + `ui_api_version` gate) and §14
(per-plugin JS deps / federation remotes). It is the frontend half of the kernel/plugin platform
whose backend half is spec 93.

Convention: `[ ]` todo · `[x]` done + verified green · `[~]` partial/scaffolded (see `BUILD-LOG.md`).
Nothing is dropped silently — an unchecked box at the end is an explicitly-logged parity gap.

## Progress snapshot

**DONE + browser-proven** (headless Chromium, `web/scripts/render-proof.mjs`):
- **Part A (platform machinery) — complete.** SDK (`@radd/plugin-sdk`): slots, primitives, tokens,
  hooks, `UI_API_VERSION` gate. Host: native-ESM federation (import map + `globalThis.__RADD_SHARED__`
  + generated `/shared/*.js` singleton shims — no MF plugin, no rolldown-compat risk), the runtime
  loader (version-gate → import → activate → quarantine → live enable/disable), `<Slot>` in base
  views. Backend: `ui_api_version` on the manifest, `/capabilities` `remotes[]`, plugin-assets
  serving, `radd.plugins` entry-point discovery, entity-table create on runtime enable.
- **Part B slots implemented + browser-proven:** `issue.panel.section`, `route.page` (splat-route
  `PluginPage`), and `settings.page` (settings splat-route `SettingsPluginPage` + manifest-driven
  settings nav). The registry supports every slot id in the vocabulary; the rest (`issue.tab`,
  `dashboard.widget`, `item.action`) wire up as their first consumer is migrated. `sidebar.nav` is
  already manifest-driven.
- **Part C migrated:** `participants` (issue.panel.section) + `milestones` (route.page, real CRUD).
- **Part D acceptance — complete.** `examples/acme-notes` loads at runtime with zero core edits and
  exercises all three proven slot types (route.page Notes page + issue.panel.section Notes card +
  settings.page Notes settings).
- **Part E — proven:** full backend `pytest` (965) green; host + every remote + the example build;
  the headless proof renders the participants section, the milestones page, and the external
  acme-notes page+section, exercises the version gate, and toggles a section live via enable/disable;
  no hardcoded hex in remotes (grep-clean).

**PENDING (logged gaps, not blockers — each still works in `web/src` until migrated):** Part C's
remaining surfaces — the `csat`/`approvals`/`mailintake`/`vcs` issue sections and the
docs/dashboards/cycles/forms/reporting nav pages and the settings pages. Each is a mechanical repeat
of the participants extraction; `web/src` will import nothing plugin-specific only when Part C is
fully `[x]`.

The four **LOCKED** user decisions this spec must satisfy:
1. **Full parity** — every plugin's UI moves out of `web/src` into the owning plugin as a federated
   remote; end state: `web/src` imports nothing plugin-specific (host shell + slots + shared SDK only).
2. **Acceptance = an in-repo external example plugin** (`examples/acme-notes/`) — its OWN project
   (own `package.json` + vite-federation + `pyproject`), built SEPARATELY, adding an entity
   (`kernel.entities`) + an issue-panel slot section + a nav page, loaded at runtime with ZERO edits
   to core or other plugins.
3. **Verify with a headless browser** that federated UIs actually RENDER (milestones page,
   participants on an issue, enable/disable live); if the sandbox can't run one, fall back to
   build-level proof (typecheck + build every remote + boot + loader smoke) and DOCUMENT the gap.
4. **Shared theming is first-class** — ONE token source (Tailwind v4 `@theme` CSS vars on `:root`
   via the SDK) + shared primitives (Button/Field/Chip/Card). Plugins use tokens/primitives; NO
   plugin hardcodes hex (grep-verified). Remotes render into the host DOM → inherit host CSS vars.

---

## Part A — The platform machinery (load-bearing)

### A0. The public frontend SDK — `@radd/plugin-sdk`
- [ ] An in-repo npm package (`web/packages/plugin-sdk`) that is the ONLY frontend surface a plugin
      imports. Semver'd; exports a `UI_API_VERSION` constant + a compat gate. Shared as a federation
      **singleton** so the slot registry, primitives, hooks and theme are one instance across host +
      all remotes.
- [ ] **Slot registry** — `registerSlot(slotId, contribution, {plugin})`, `unregisterPlugin(name)`,
      `useSlot(slotId)`, and `<Slot id props/>`. A `useSyncExternalStore`-backed store so `<Slot>`
      re-renders when a remote registers/unregisters (enable/disable live).
- [ ] **Slot id constants** (§ Part B).
- [ ] **Shared primitives** — `Button`, `Field`/`TextField`, `Select`, `Chip`, `Card`, `Modal`,
      `Spinner`, `EmptyState` — styled from tokens via SDK-owned CSS classes (`.radd-*`), so a remote
      renders them identically without depending on its own Tailwind scan of node_modules.
- [ ] **Theme tokens** — a `tokens.css` (`:root` semantic `--radd-*` vars over the zinc scale, light
      + dark + compact) + a JS token object; a `components.css` for the primitive classes. The host
      imports both once; remotes inherit via the shared DOM.
- [ ] **Hooks** — `useApi` (the typed fetch client), `useAuth`/`usePermissions`, `useCapabilities`,
      `useItemsQuery`/`useItemQuery` (SLQ + item reads), and the shared `@tanstack/react-query`
      client — all singletons.

### A1. The host — Vite module-federation host
- [ ] `web/` builds as an MF host (`@module-federation/vite`) sharing SINGLETONS: `react`,
      `react-dom`, `@tanstack/react-query`, `@tanstack/react-router`, `@radd/plugin-sdk`
      (version-pinned). The host exposes nothing itself; the SDK is the shared contract.
- [ ] **Runtime loader** (`web/src/lib/plugin-loader.ts`) — on boot, fetch `/capabilities`, read each
      ENABLED plugin's `remoteEntry` + `ui_api_version`; **version-gate** (semver major vs the host's
      `UI_API_VERSION`); `registerRemotes` + `loadRemote`; call the remote's `activate(sdk)` which
      registers its slots. **Quarantine**: a remote that fails to load/activate is caught, logged,
      marked errored, and never aborts boot or other remotes.
- [ ] **Live enable/disable** — the plugin manager's enable loads+activates the remote; disable calls
      `unregisterPlugin(name)` so its slot contributions vanish from every `<Slot>` immediately
      (unmount live), and re-enable re-loads it — no page reload.

### A2. Base views render slots (host knows no plugin)
- [ ] `web/src` renders `<Slot>` at every extension point (Part B) and imports NOTHING plugin-specific.
      The issue view, sidebar, settings tree, dashboards, and item action menus host slots.

### A3. Backend UI-manifest wiring
- [ ] `PluginUiManifest` carries `remote` (remoteEntry URL) + `ui_api_version`; `/capabilities`
      returns a `remotes: [{name, remoteEntry, ui_api_version}]` list of every ENABLED plugin with a
      UI remote (disable removes it → host unmounts).
- [ ] Builtin remotes build to `web/dist/plugins/<name>/` and are served same-origin by the existing
      SPA static route (verified: the catch-all serves any real file). The example plugin serves its
      own `remoteEntry.js` (own build output) — loaded cross-path, same or another origin.
- [ ] No CSP is set today, so `import()` works; if one is added it must allow `script-src` for the
      remote origins. Documented.

### A4. Theming parity (LOCKED #4)
- [ ] ONE token source in the SDK; host + every remote reference `--radd-*` tokens / `.radd-*`
      classes / SDK primitives. `grep -rE '#[0-9a-fA-F]{3,6}'` over every remote's source is clean
      (icons/illustrations excepted + noted). Light/dark/compact all inherited from the host `:root`.

---

## Part B — The slot vocabulary

Each base view renders `<Slot id=…>`; plugins contribute via `registerSlot`.

- [ ] `issue.panel.section` — cards in the issue right-rail (participants, CSAT, approvals, external
      requester, VCS summary…). Receives `{item, project}`.
- [ ] `issue.tab` — extra tabs on the issue detail (VCS/commits, history addenda…). `{item}`.
- [ ] `sidebar.nav` — nav rows in the left rail (already partly done via the nav manifest; unify).
- [ ] `route.page` — a full plugin page mounted at the nav item's `path` (milestones CRUD, dashboards
      admin, connector settings…). The host renders the matching remote page for an unknown route.
- [ ] `settings.page` — a page under `Settings → …` (per-plugin admin). `{}`.
- [ ] `dashboard.widget` — a dashboard widget type. `{config}`.
- [ ] `item.action` — an entry in an item's action menu. `{item}`.

---

## Part C — Per-plugin UI migration inventory (LOCKED #1 — full parity)

Every plugin-specific surface currently in `web/src`, and where it goes. Each `[x]` = extracted into
the owning plugin's remote + the host renders it via a slot + `web/src` no longer imports it.

**Issue-view sections** (`components/items/IssueProperties.tsx`) — **DONE: the band-aids are gone and
IssueProperties imports NOTHING plugin-specific; all sections arrive via the `issue.panel.section`
Slot from their own remotes:**
- [x] `participants` → `issue.panel.section` (ParticipantsSection). `web/remotes/participants`.
- [x] `csat` → `issue.panel.section` (CsatChip). `web/remotes/csat`.
- [x] `approvals` → `issue.panel.section` (ApprovalsCard). `web/remotes/approvals`.
- [x] `mailintake` → `issue.panel.section` (ExternalRequesterChip). `web/remotes/mailintake`.
- [ ] `vcs` → `issue.panel.section` / `issue.tab` (VCS refs + commits). *(still in web/src)*

**Nav / route pages** (`components/shell/Sidebar.tsx` + `router.tsx`):
- [x] `milestones` → `route.page` (real CRUD page). `web/remotes/milestones`.
- [ ] `docs` → sidebar spaces section + doc pages → `route.page` + `sidebar.nav`.
- [ ] `dashboards` → sidebar section + dashboard page + widgets → `route.page` + `dashboard.widget`.
- [ ] `cycles` → sidebar section + cycle page → `sidebar.nav` + `route.page`.
- [ ] `forms` → per-project form links + submit page.
- [ ] `reporting` → reports pages.
- [ ] `timelogging` → timesheet page.

**Settings pages** (`routes/settings/*` + `routes/project-settings/*`):
- [ ] `slas`, `ai`, `mcp`, `docs`, `dashboards`, `jiraimport`, `canned`, `automations`, `forms`,
      `fields`, `screens`, `itemtypes`, `linktypes`, `cycles`, `releases`, `timelogging`, `labels`,
      `directory`(ldap), and the auth/roles/teams/users admin — each → `settings.page`.

**Connectors / auth-method settings:** `gitlab`, `forgejo`, `googlechat`, `alertmanager`,
`mailintake`, `sso`, `ldap` → `settings.page`.

> Realism note: this inventory is exhaustive by intent (drop nothing). The run migrates the flagship
> slot-based surfaces + a real CRUD page + representative settings pages to PROVE the mechanism end to
> end, then drives the rest as far as the run allows; every surface not yet `[x]` is an explicitly
> logged gap in `BUILD-LOG.md` with the exact mechanical pattern to finish it. A surface still in
> `web/src` keeps working until migrated (no regression), but LOCKED #1's end-state (web/src imports
> nothing plugin-specific) is only reached when every box here is `[x]`.

---

## Part D — Acceptance: the external example plugin (LOCKED #2)

- [ ] `examples/acme-notes/` is a fully INDEPENDENT project: its own `pyproject.toml` (a Radd plugin
      package with a `radd.plugins` entry point) + its own `web/` with its OWN `package.json` +
      vite-federation config, depending on `@radd/plugin-sdk` (via a `file:` link in-repo; a real
      external plugin installs the published SDK).
- [ ] Backend: an `acme.notes` `EntitySpec` (a note entity) → auto-wired table + CRUD + events + RBAC,
      a nav item, and a `ui=PluginUiManifest(remote=…, ui_api_version=…)`.
- [ ] Frontend: the remote registers a `route.page` (Notes CRUD) + an `issue.panel.section` (notes on
      an issue), built with `npm run build` in its OWN project to its OWN `remoteEntry.js`.
- [ ] Installed + enabled at runtime via the plugin manager with **ZERO edits to core or any other
      plugin** — its UI appears; disabling it removes its UI live.

---

## Part E — Verification gates (all must hold for DONE)
- [ ] `alembic upgrade head` clean; `create_app()` boots; backend `pytest` green (no regression on the
      spec-93 baseline).
- [ ] `web` host builds (tsc + vite) AND every remote builds (SDK, each builtin remote, the example
      plugin) — a build script builds them all.
- [ ] Loader smoke: booting the app serves `/capabilities` with the `remotes` list; the host imports
      each without error.
- [ ] **Render proof (LOCKED #3):** a headless-browser run shows the milestones page rendering, the
      participants section on an issue, and enable/disable toggling a federated section live — OR, if
      headless can't run here, the build-level proof above + a documented browser-unverified gap.
- [ ] `ui_api_version` gate: a remote built against an incompatible major is refused (not loaded), the
      rest still load.
- [ ] Theming: no hardcoded hex in remote source (grep); light/dark inherited.
- [ ] `docs/modules.md` updated (the `ui`/federation addendum); `BUILD-LOG.md` current.

## Addendum — plugin-UI depth (shipped + verified)

Built on the platform above; all in `@radd/plugin-sdk` + a thin host wiring, all headless-proven.

- **View-type + widget-type slots.** New `SlotId.viewType` / `SlotId.dashboardWidget` (keyed by the
  type key), backed by kernel `registries.view_types` / `widget_types` (`ViewTypeSpec` /
  `WidgetTypeSpec` on `RaddPlugin`) surfaced in `/capabilities`. A plugin ships a whole saved-view
  surface or a dashboard-widget renderer. Missing type (plugin disabled/uninstalled) → a clear
  `MissingPluginType` notice, never a blank render.
- **Per-contribution toggles, two scopes, plugin-owned.** A contribution renders iff enabled in BOTH
  scopes: **GLOBAL** (instance-wide, admin — Settings → Plugins → `<plugin>`, stored per-plugin in
  `InstalledPlugin.config`; `GET /plugins/contribution-settings` any-user + `PUT
  /plugins/{id}/contribution-settings` admin) and **PER-USER** (Profile; `users.preferences` JSONB +
  `GET/PUT /auth/me/preferences`). The kernel forces nothing: a plugin exposes toggles by mounting
  `<GlobalContributionToggles>` / `<UserContributionToggles>` (On/Off **switch**, not checkboxes)
  into the new `pluginManagerSection` / `profileSection` slots; `toggleable:false` keeps a plugin's
  own control surfaces out of the lists.
- **Disabled contributions leave every manifest-driven surface.** `useDisabledNavPaths()` +
  `useDisabledMatches(slot)` report the turned-off route/settings paths and view/widget-type keys, so
  the main + settings sidebars drop the nav link, the view-type / widget-type dropdowns drop the
  option, and a direct visit / existing view of a turned-off type shows the "turned off" notice
  instead of a live-but-broken control.

`docs/plugin-ui.md` has the full slot vocabulary + the toggle/nav/dropdown rules.
