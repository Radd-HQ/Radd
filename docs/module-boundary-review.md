# Module and plugin architecture review

Tracking: RADD-1218. Reviewed code baseline: `e02e3e1`.

The direction is sound: RADD is a modular monolith with a real plugin kernel.
It is not yet a system in which every feature can safely be detached at runtime.
The most urgent gaps are lifecycle correctness, followed by database ownership
exceptions and frontend host coupling. Moving files alone would not resolve them.

## Scope and evidence

Read-only review of backend manifests/imports, kernel registration, runtime
enable/disable/uninstall, frontend remote loading, source reachability, and
selected cross-module administrative operations. No application code or live
deployment was changed by this review.

- 56 backend manifests: 34 core and 22 optional.
- AST scan found 338 distinct directed cross-module dependencies across 1,477
  import sites. These are dependency relationships, not 338 violations.
- 39 tests passed across `test_module_contracts.py`, `test_plugin_manager.py`,
  `test_plugin_atom_sweep.py`, `test_kernel.py`, and `test_merge_coverage.py`.
- Disposable Python probes exercised actual registration/unregistration and the
  uninstall route with synthetic plugins, fake admin context, and no database.
- Disposable JavaScript probes exercised the actual frontend loader with mocked
  SDK/import seams: failed activation, disable during loading, and changed URL.
- Frontend AST reachability covered 586 TS/TSX files from `main.tsx` and
  `shared-runtime.ts`, including literal dynamic imports. This is not a proof
  that every reachable export is used, or that every supported external API is dead.

This was not a full runtime/security audit of all feature combinations.

## What is working

The kernel does not import concrete plugins. Declarative `RaddPlugin`
contributions, registries, host contracts, and entity generation are real
abstractions. The architecture ratchet checks declared dependencies and forbids
non-spine model imports; its model-import exception allowlist is empty.

The intentional shared spine (`auth`, `projects`, `items`, `workflow`, `teams`,
`fields`) is a reasonable foundation. Public service barrels and the lazy SDK
facade serve a purpose. Importer fan-out is also expected for orchestration.
Neither shared infrastructure nor a large dependency count alone proves a
boundary violation.

## Findings in priority order

### 1. Rejected uninstall can still remove a plugin from the running app — high

[`pluginmgr/router.py`](../server/src/radd/modules/pluginmgr/router.py) invokes
shutdown hooks and unmounts before
[`service.uninstall`](../server/src/radd/modules/pluginmgr/service.py) validates
whether the plugin is removable and whether dependents prevent removal.

A synthetic core plugin reproduced this: uninstall raised `ConflictError`, but
one route and its registry entry had already been removed. A rejected operation
must not alter runtime state.

Validate the complete transition before side effects, then define recovery for
hook/mount/commit failures. Add route-level tests: service-only rejection tests
currently pass while missing this defect.

### 2. Hot lifecycle does not match boot lifecycle — high

[`registry.unregister_plugin`](../server/src/radd/kernel/registry.py) leaves
`tasks` and `consumer_names` registered. A synthetic task/consumer plugin
confirmed both remain after unregistering.

[`app.py`](../server/src/radd/app.py) schedules task loops at startup; hot enable
does not schedule those tasks, and hot disable does not stop app-owned loops.
Currently the builtin task contributor is core `access`, so the task gap mainly
affects the optional/external plugin contract, rather than demonstrating a
broken hot-disable of that core module.

Hot enable also bypasses the loader's API-version and required-dependency
validation. Runtime mounting changes only `request.app`; no reconciliation of
plugin enable/disable events was found for other running workers or replicas.
Persisted state is applied on subsequent boot, leaving a possible interval of
different behavior across processes.

Prefer an explicit restart-required transition for unsupported lifecycle
changes until registration, task ownership, dependency validation, rollback,
and process reconciliation are complete.

### 3. Frontend remote quarantine and reconciliation are incomplete — high

[`plugin-loader.ts`](../web/src/lib/plugin-loader.ts) registers contributions
before activation completes. Its error handler retains an errored entry but
does not unregister already-added contributions. It also tracks completed
loads by name, without an in-flight generation or URL/version identity.

Probes confirmed:

- Failed activation left one registered UI contribution.
- Disabling a remote during loading still allowed its contribution to appear.
- Changing a remote's URL under the same name did not load the new entry.

Stage or roll back activation, invalidate stale in-flight loads, and reconcile
by remote identity. These are external plugin reliability defects; they do not
mean every builtin screen is currently affected.

### 4. Database ownership has intentional but costly exceptions — medium

The import ratchet cannot see raw SQL writes into another module's tables:

- [`auth/lifecycle.py`](../server/src/radd/modules/auth/lifecycle.py) centrally
  lists other modules' user references for merge/delete. It explicitly documents
  this exception. `test_merge_coverage.py` is a valuable guard for builtin tables,
  but adding a feature still requires editing auth's ownership lists.
- [`pluginmgr/service.py`](../server/src/radd/modules/pluginmgr/service.py)
  directly updates auth-owned roles and API tokens during permission cleanup.
- [`jiraimport/rollback.py`](../server/src/radd/modules/jiraimport/rollback.py)
  and [`confluenceimport/rollback.py`](../server/src/radd/modules/confluenceimport/rollback.py)
  know other modules' tables and restore/delete directly. Quiet administrative
  undo is intentional, but schema and owner-invariant changes must be coordinated.

These are maintenance risks, not reproduced data-corruption claims. Start with
an auth-owned atom-cleanup API. Then introduce owner-contributed identity
merge/delete and import-undo operations, preserving their special side-effect
semantics and coverage checks.

### 5. Builtin frontend features still require host edits — medium

[`router.tsx`](../web/src/router.tsx),
[`settings/layout.tsx`](../web/src/routes/settings/layout.tsx), and the new
[`import-data.tsx`](../web/src/routes/settings/import-data.tsx) manually wire
features and importer cards. The remote SDK has contribution slots, but builtin
features do not consistently use equivalent contracts.

[`view.tsx`](../web/src/routes/view.tsx) is approximately 1,470 lines and
coordinates several distinct view modes. This is a concentration of change
risk, rather than evidence that all shared view logic should be duplicated.

Make importer/settings contributions declarative and extract view-mode
controllers behind stable shared contracts. Prioritize optional feature seams;
do not split the tightly related issue core merely to reduce file size.

### 6. Boot fallback catches more database failures than intended — medium

[`pluginmgr/boot.py`](../server/src/radd/modules/pluginmgr/boot.py) treats every
SQLAlchemy `ProgrammingError` as a missing installation table. An unrelated
schema error could therefore suppress persisted plugin overrides and apply
defaults. Narrow the fallback to the intended missing-table condition; fail
clearly for other schema failures.

### 7. Small confirmed dead-code residue; compatibility needs a policy — low

[`web/src/lib/queue.ts`](../web/src/lib/queue.ts) is the sole unreachable file
in the checked frontend graph. Its `orderBySlaUrgency` export has no repository
callers and implements the superseded client-page sort. It is a concrete
deletion candidate; this audit has not deleted it.

The backend still accepts the old `module` export as well as `plugin`, while
builtins use `RaddPlugin`. This may support external plugins: establish and test
a compatibility/deprecation policy before removing it.

Some documentation still describes `RaddModule`/`radd/module.py`, and a filter
comment references deleted `demo_views.sh`. Refresh current guidance, while
retaining historical specifications and migrations that still serve a purpose.

## Recommended sequence

1. Fix lifecycle validation/cleanup and remote-loader races, with failure-path
   tests and explicit restart semantics where hot transitions are unsupported.
2. Extend architecture checks to cover lifecycle parity and approved raw SQL
   ownership exceptions; keep the existing import ratchet.
3. Move administrative writes behind owner APIs and contribution contracts.
4. Give builtin importer/settings UI the same contribution approach as plugins;
   split view orchestration by behavior with regression coverage.
5. Remove confirmed dead code and refresh stale references. Deprecate external
   compatibility only after documenting the supported contract.

No wholesale rewrite is indicated. The kernel foundation is useful; closing
these gaps would make the plugin relationship an operational guarantee as well
as an organizational convention.
