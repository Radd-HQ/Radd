# 125 — Managed plugin packages and live UI changes

Tracking: RADD-1220. Extends spec 124 with package upload and persistent storage.

## Delivered experience

Settings → Plugins accepts a built `.whl` package and offers **Upload and install**.
The administrator confirms that the package is trusted server code. Upload
validates and publishes its code/UI to the managed directory; registration is
then a separate request. If registration fails, the package remains visible and
Install can be retried. Activation remains a separate, deliberate action.

The container image does not need rebuilding for compatible pure-Python plugins.
`RADD_PLUGINS_DIR` defaults to `var/plugins` for host development and `/data/plugins`
in the image. Every web and worker must mount the same persistent POSIX filesystem
with working file locks and atomic rename. The Helm chart adds a dedicated
`<release>-plugins` PVC even when attachments use S3. Its access mode is configurable;
use storage that supports the intended replica/node topology.

## Package ownership and validation

The store owns a catalog, checksum-addressed package directories, and process
reports. Uploaded files never modify the host Python environment.

- Authenticate as an instance administrator before reading the raw request body.
- Limit compressed upload to 32 MiB, expanded content to 128 MiB and archive entries
  to 10,000. Reject path traversal, links, foreign top-level paths, `.pth` files,
  native libraries, duplicate paths and unsupported wheel layouts.
- Accept one pure-Python distribution with one `radd.plugins` entry point. Reject
  module/identity collisions and incompatible Python/dependency requirements.
- Do not run pip, build hooks or fetch dependencies. Required Python packages must
  already be compatible with the deployment. Plugins needing other dependencies
  or native libraries still use deployment installation.
- Import the staged manifest in a disposable interpreter with a timeout; check
  the SDK, identity, version and packaged UI. This is validation, not a security
  sandbox: trusted plugin code executes with server privileges.
- Publish through an atomic catalog replace under a shared filesystem lock.
  Normal failures remove staging. The next installer prunes interrupted staging
  and unpublished checksum directories under that same lock.

Uploads and package removals emit audit events. Filesystem publication and the
subsequent database audit/registration transactions are not a distributed
transaction: a failed DB commit can leave a discoverable, unregistered package.
The UI explicitly supports retrying registration.

## Supported live changes

Each web/worker runs its own reconciliation loop, reading committed desired state
approximately every two seconds. Idle polls avoid rediscovery, and a busy
installer causes the poll to skip rather than block the API event loop.

Only optional installable manifests containing identity, dependency and UI
metadata qualify. Any backend routers, entities, hooks, tasks, exception handlers,
or other contributions make the plugin restart-required. This conservative
allowlist is derived from all manifest fields, so adding a new contribution kind
cannot accidentally make it hot-loadable.

Live registration checks loaded dependencies and changes the local UI registries.
Disabling withdraws those contributions. Every process writes an atomic report
of its active plugin ids and reconciliation errors. Settings polls local status;
browser shells refresh capabilities every 15 seconds, allowing remote loaders
to add/remove updated UI without a full page reload. The frontend loader retains
spec 124's failed-activation rollback and stale-load suppression.

This does not implement arbitrary Python module replacement. Uploading another
version of an existing package is rejected. Disable, forget, remove files, restart
all processes to clear Python's module cache, then upload the replacement.

## Uninstall and cleanup

1. Disable the plugin. For live UI plugins, wait for reconciliation; restart all
   processes for backend plugins.
2. Forget registration and plugin-specific grants. Stored business data remains.
3. Use **Remove files** on the discovered managed package. The store refuses while
   any known process reports it active, has an error, or has a stale report.
4. Remove the owned code/UI directory and catalog entry; preserve plugin data.

Clean process shutdown removes its report. After a crash, a stale report blocks
cleanup deliberately. An operator must verify that the named process/pod has
terminated before removing its exact report from `plugins/runtime/`. A stale
heartbeat alone cannot prove that a paused or disconnected process has stopped.
Never remove reports for running processes to force a package removal.

Back up the plugin volume alongside the database; database-only backups do not
contain uploaded code. Keep the original versioned wheel as a recovery artifact.

## Evidence and remaining live-lifecycle work

Tests exercise invalid/archive escape uploads, dependency and manifest failures,
interrupted installer cleanup, admin-before-body checks, streaming limits, and
live enable/disable/removal. A two-interpreter test shares the store and proves
one disabled process is insufficient for removal; both must acknowledge. A
built-SPA browser proof covers actual binary transport, confirmation, registration,
search, errors and restart messaging. Helm renders are checked with S3 and workers.

Before widening live support to backend plugins, implement:

- Ownership handles for every route, entity, registry contribution and task.
- Dependency-ordered activation with compensation for partial startup failure.
- Request/job draining before unmount; hooks with deadlines and explicit failures.
- Generation-based activation and acknowledgements across an authoritative
  process membership set, including newly joining and partitioned replicas.
- Versioned code loading without reusing Python module globals; a separate worker
  process may be appropriate for plugins with incompatible dependencies.
- Plugin-owned schema upgrade contracts and compatibility checks. Database
  migrations must never be inferred from uploaded model differences.

The present process reports are operational acknowledgements for the shared
store, not a distributed consensus or process-fencing protocol. Backend lifecycle
changes and code replacement therefore remain restart-required.
