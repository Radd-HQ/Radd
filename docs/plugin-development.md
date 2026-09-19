# Build and manage an external RADD plugin

Use the RADD release you intend to deploy. Plugins live in their own repositories;
the RADD checkout supplies the SDK and development environment.

## Install a packaged plugin without rebuilding RADD

Open **Settings → Plugins**, choose a built `.whl`, and click **Upload and install**.
After registration, enable it. Compatible UI-only plugins apply live across web
and workers; backend plugins show a restart requirement. The wheel must include
its built UI and use Python dependencies already available in RADD.

The code is stored in `RADD_PLUGINS_DIR` (`/data/plugins` in containers). Mount the
same persistent directory in every web and worker. The Helm chart supplies a
separate plugin PVC, including when attachments use S3. Use ReadWriteMany storage
for multi-node replicas; the filesystem must support locking and atomic rename.
Back up this volume alongside the database.

To remove an upload: **Disable → wait/restart → Forget → Remove files**. Business
data remains. File removal waits for process acknowledgements. Stale reports
require an operator to confirm that the recorded process has stopped before
removing that report. Replacing the same Python module requires a restart after
removal; live backend code replacement is not supported yet.

See [spec 125](specs/125-managed-plugin-packages.md) for the live subset, cleanup
rules and remaining work. The image-based recipe below remains available for
plugins that need additional dependencies or native libraries.

## Create and link

From RADD's `server/` directory:

```sh
uv run python -m radd.plugin_cli new /work/acme-tools --name acme-tools \
  --sdk ../web/packages/plugin-sdk
uv run python -m radd.plugin_cli check /work/acme-tools
uv run python -m radd.plugin_cli develop /work/acme-tools
```

Omit `--sdk` for a backend-only plugin. The UI option copies the SDK into the
new repository; commit that snapshot. It does not point back to your RADD checkout.
`develop` adds an editable package to the current Python environment; run it again
if an exact `uv sync` removes packages not in RADD's lockfile. It does not install
additional plugin dependencies; install those explicitly in the development
environment and verify compatibility with RADD.

For a UI plugin, first enter `/work/acme-tools/src/acme_tools/ui`, run
`npm install` and commit `package-lock.json`. Then run `npm run build`.
The generated frontend uses Node 22.12+ and the target release's SDK/toolchain.

Open **Settings → Plugins**, find `acme-tools`, click **Install**, then **Enable**.
Restart the RADD web and worker processes. Its page appears in the sidebar.
The status distinguishes requested activation from what this server has loaded.

## Edit

- Backend declaration: `src/acme_tools/__init__.py`. Add entities, routes, events,
  permissions or other contributions through `radd.sdk`.
- Frontend contribution: `src/acme_tools/ui/src/index.tsx`. Use
  `@radd/plugin-sdk` slots and components.
- Python edits: restart the development processes. If using a reload server,
  include the external repository in its reload directories.
- UI edits: run `npm run watch` inside the UI directory, then refresh the browser.
  The host serves the plugin's rebuilt bundle directly; no host rebuild is needed.

The [UI reference](plugin-ui.md) and
[acme-notes example](../examples/acme-notes/README.md) cover issue tabs, panels,
settings, entities, permissions and queries. A starter page has no privileged
operations; add permission guards when adding data access.

## Package and deploy

Keep the Python project version and `RaddPlugin.version` equal. From RADD's
server environment:

```sh
uv run python -m radd.plugin_cli check /work/acme-tools
uv run python -m radd.plugin_cli build /work/acme-tools
```

`dist/` contains a wheel with the built UI, `plugin.json` with its SHA-256,
and a Containerfile. From the plugin repository:

```sh
podman build --build-arg RADD_IMAGE=ghcr.io/radd-hq/radd:YOUR_PINNED_VERSION \
  -f dist/Containerfile -t registry.example.com/company/radd:YOUR_PLUGIN_RELEASE dist
```

Push your image and update the deployment repository to use it for web, workers,
and migration jobs. The generated Containerfile uses `--no-deps` and `uv pip check`:
missing/incompatible Python dependencies fail the image build. If your plugin adds
libraries, extend the recipe with reviewed, pinned dependencies. Do not let plugin
installation silently replace RADD's runtime dependencies.

Deploy the image, register/enable in Settings, then restart **all** processes to
apply activation. No browser request runs pip or rewrites containers.

## Update, disable and remove

Update by building a new versioned wheel/image and deploying it. Existing enabled
state persists. A UI-only edit at the same URL needs a browser refresh; release
versions should change their artifact version.

Disable in Settings and restart every web/worker process. Plugin data remains.
Once unloaded, **Forget** removes registration and plugin-specific grants, but
keeps data and the Python package. Reinstallation requires reviewing permissions
again. Remove the package from the next image when no longer needed.

The page reports **this server's** loaded state, not a health check of every worker.
Missing packages and import errors appear as problems. Restore the package to
manage its registration and permissions; do not delete its database tables by hand.

Initial declarative entity tables are created at boot. Table alterations and
other schema upgrades need an explicit, reviewed deployment migration; this
workflow does not run arbitrary plugin migrations or destructive downgrades.


## Scripts: Python without a plugin (RADD-1269)

Not every extension needs a plugin. A **Run a script** or **Decide with a
script** automation node holds admin-authored Python right on the node, run
out of process in a managed interpreter with its own packages, as the
automation's identity. The automation's versions are the script's history;
Settings → Scripts (under Server) owns the interpreter and the packages.

**The contract.** A script defines `main(ctx)`:

```python
def main(ctx):
    ctx.event        # the event that fired (type, actor, payload) — None on a manual/scheduled run
    ctx.items        # the issues this node is acting on, as full read models (list of dicts)
    ctx.item         # the first of them, for the per-item case
    ctx.vars         # values upstream nodes produced: ctx.vars["triage"]["priority"]
    ctx.params       # this node's own params
    ctx.client       # a ready radd_sdk.RaddClient, acting as the automation's identity
    ctx.log("text")  # a line on the run's stderr, shown in the run report
    return {"count": len(ctx.items)}
```

A **Run a script** node publishes the dict `main` returns: each key you
declared as an output becomes `{{name.key}}` downstream. A **Decide with a
script** node takes the port `main` names; a failure, a timeout or an unknown
name takes `unavailable`.

**What a script can and cannot do.** It runs in a subprocess of the managed
interpreter with a minimal environment — no database URL, no server secrets —
and a short-lived API key minted for the automation's identity, so whatever it
does through `ctx.client` is exactly what that identity could do by hand, and is
attributed to it. It is killed at its timeout. Its stdout and stderr are kept
(tail-capped) on the run.

**The interpreter.** One uv-built virtual environment per instance
(`RADD_SCRIPTS_DIR`, `/data/scripts` in the image). Pick the Python version and
Rebuild; the Radd SDK client (`sdk/`, shipped in the image at `/app/sdk`) is
installed into it, then every package in the Packages list. A package is a
name with optional extras and version specifiers (`requests>=2.31`); URLs,
paths and options are refused, because "install from wherever this string
points" is not something an admin should be able to do by accident.

**Where it fits.** The out-of-process `sdk/` runner (`radd-runner`) is the same
idea for code that lives OUTSIDE the instance and reacts to the event stream;
scripts are for code that belongs to an automation and wants the packet the
graph assembled. Both speak the same client.
