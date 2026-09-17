# Build and manage an external RADD plugin

Use the RADD release you intend to deploy. Plugins live in their own repositories;
the RADD checkout supplies the SDK and development environment.

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
