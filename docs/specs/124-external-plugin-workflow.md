# 124 — External plugin development and management

Tracking: RADD-1219. Implements the package-and-deployment-first workflow.
[Spec 125](125-managed-plugin-packages.md) extends it with uploads, a persistent
plugin directory and conservative live UI activation.

## User outcome

A developer creates an independent repository, validates it against the RADD
SDK, builds one versioned wheel containing backend code and optional UI, and
hands a reproducible artifact to the deployment owner. An administrator sees
the delivered package in Settings → Plugins, registers it, reviews requirements,
and requests activation. Restarting all web and worker processes applies that
state consistently at boot.

No core-repository changes are needed for a plugin. Python dependencies share
the host environment. Packages are trusted in-process code, not sandboxed apps.

## Commands and artifacts

`python -m radd.plugin_cli` provides:

- `new PATH --name acme-tools`: scaffold an independent Python package.
- `new PATH --name acme-tools --sdk PATH`: also scaffold a UI remote, vendoring
  a snapshot of the public frontend SDK so the plugin has no repo-relative SDK
  dependency. Use the SDK from the target RADD release.
- `check PATH`: validate the manifest, package identity/version, API compatibility,
  available dependencies, duplicate identities, public backend import boundary,
  and packaged UI location. Imports trusted plugin code but runs no startup hooks.
- `develop PATH`: editable install into this interpreter's environment, without
  modifying core dependencies, followed by a dependency consistency check.
- `build PATH`: check, build UI from its committed npm lockfile, build a fresh
  wheel, verify that UI is in the wheel, and emit SHA-256 metadata plus a derived
  image Containerfile. `--toolchain NODE_MODULES` supports an explicitly prepared
  local toolchain without npm; normal CI uses the plugin's own lockfile.

The generated image installs the exact wheel with `--no-deps`, verifies its
checksum and checks Python dependency consistency. Additional dependencies must
be explicitly pinned and installed in the deployment recipe; a plugin build
must not silently upgrade RADD's libraries. `RADD_IMAGE` must identify a pinned
base image. Web, worker and migration jobs use the same resulting image.

## Lifecycle contract

| Action | Saved state | Immediate runtime effect | Data |
| --- | --- | --- | --- |
| Install | installed | None | Retained |
| Enable | enabled | None; restart all processes | Retained |
| Disable | disabled | None; restart all processes | Retained |
| Forget | registration removed | Only allowed once unloaded on this server | Retained; plugin-specific grants are removed |
| Update | New wheel in a new image | Applied by deployment restart | Requires compatible schema or an explicit migration |

This intentionally replaces best-effort live backend mount/unmount. Request-time
mutation could leave routes, hooks, tasks and other processes inconsistent even
when the request was rejected or its transaction failed. The management API
reports desired `state`, local `active`, local `restart_required`, `origin`,
`dependencies` and `problems`. It makes no claim of cluster-wide convergence.
Operators must restart **all** processes before forgetting or removing a package.

Validation precedes persistence. Both desired and currently loaded dependents
block disabling/removal. Boot orders plugins by required dependencies and fails
clearly for missing/cyclic requirements. Only an undefined installation table
permits the fresh-database fallback. Broken entry points, identity collisions,
and missing previously registered packages are visible to administrators.

Frontend remote reconciliation tracks in-flight loads and URL/API identity,
ignores stale activation registrations, rolls back failed contributions and
runs teardown. This improves frontend cleanup but does not sandbox arbitrary
side effects in trusted plugin code. UI developers must return cleanup through
`deactivate` for their own listeners/timers.

## Developer loop

Scaffold → check → editable link → install/enable → restart → edit → restart
Python or rebuild UI and refresh browser. A watch UI build avoids rebuilding the
host frontend. Build/release the wheel only when ready to share it.

A UI scaffold starts with an isolated page. The existing acme-notes example
shows deeper entity/issue/settings/view integration. Plugin backends use
`radd.sdk`; UI uses `@radd/plugin-sdk`. Neither should import host internals.

## Validation and limits

Tests cover rejected transition immutability, restart-only activation, API and
version mismatches, dependency ordering/cycles, registry cleanup, schema-error
handling, and remote activation races. A generated external UI plugin is built
outside the repository and its wheel installed/discovered/loaded in a disposable
location. A built-SPA browser proof covers the management controls and pending
restart message.

This version does not implement a package marketplace, browser upload, arbitrary
Git URL execution, automatic deployment credentials, distributed process
heartbeats, or automatic plugin schema migration/rollback. Declarative entities
support initial table creation; existing tables are not automatically evolved.
Schema-changing plugins must supply an explicit migration run during deployment.
Future migration tooling should declare ordered, plugin-owned upgrades and
preflight compatibility without promising destructive downgrade safety.
