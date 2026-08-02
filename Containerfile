# Radd app image (spec 48; trixie + dev target). Build from the repo root:
#   podman build -t radd -f Containerfile .            # production (SPA baked in)
#   podman build -t radd-dev --target dev -f Containerfile .   # dev (skips the SPA stage)
#
# Three stages: `web` builds the SPA, `base` is everything the server needs, and
# the two leaves differ only in whether the built bundle is copied in. `dev` does
# not depend on `web` at all, so a dev build never runs npm — the SPA arrives as
# a bind mount instead (compose.dev.yaml).

FROM docker.io/library/node:22-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
# The WORKSPACE manifests must exist before `npm ci` — web/package.json declares
# `workspaces: [packages/*, remotes/*]`, and npm resolves `@radd/plugin-sdk` from
# the tree, not the registry. Without this the install dies on a 404 (which is
# what broke this image between spec 94 and 99). Copying the whole directory
# keeps a future workspace package working with no edit here.
COPY web/packages ./packages
RUN npm ci
COPY web/ ./
# Plugin UI remotes (spec 94) live in the SERVER tree (<module>/ui) and build IN
# PLACE to <module>/ui/dist, which the app serves at /plugins/<name>/. build-all
# scans ../server/src/radd/modules, so the repo layout is mirrored here — a bare
# `npm run build` produces the host only, which is how every plugin remote 404'd
# in production while working locally (ui/dist is gitignored, so nothing was
# copied in either). The node_modules symlinks build-all plants in each ui dir
# point at /build/web/node_modules and would arrive dangling in the runtime
# image — delete them after the build.
COPY server/src/radd/modules /build/server/src/radd/modules
RUN node scripts/build-all.mjs \
 && find /build/server -type l -name node_modules -delete


FROM docker.io/library/python:3.12-slim-trixie AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# postgresql-client is a RUNTIME REQUIREMENT (spec 99): the app refuses to start
# without pg_dump/pg_restore, and the client major must be >= the server it dumps.
# Debian trixie carries client 17 in the DEFAULT repos, which is why this image is
# trixie and not bookworm — bookworm ships 15 (too old for a PG 16 server) and
# would need the PGDG apt repo, a key, and a purge step to avoid shipping curl.
RUN apt-get update && apt-get install -y --no-install-recommends \
      postgresql-client-17 \
 && rm -rf /var/lib/apt/lists/*

# Use the image's interpreter — a uv-managed Python would land under /root,
# unreadable by the runtime user.
#
# The venv lives OUTSIDE /app/server on purpose: dev bind-mounts the repo's
# ./server over /app/server, which would otherwise shadow .venv and leave the
# container with no dependencies. uv installs the project itself as editable, so
# the mounted source is what actually runs.
ENV UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --extra localembed
COPY server/ ./
RUN uv sync --locked --no-dev --extra localembed

ENV RADD_WEB_DIST=/app/web/dist \
    RADD_ATTACHMENTS_DIR=/data/attachments \
    RADD_AI_LOCAL_EMBED_CACHE=/data/models \
    RADD_BACKUP_DIR=/opt/radd/backups \
    RADD_BACKUP_KEY_FILE=/data/radd-backup.key \
    PATH="/opt/venv/bin:$PATH"

# Fixed uid: a NAMED volume inherits the image's ownership and just works, but a
# BIND mount (-v ./backups:/opt/radd/backups) arrives owned by the host user and
# is unwritable to this process. A predictable uid is what makes
# `chown 10001:10001 ./backups` a documentable step (docs/deploy.md); Kubernetes
# solves it properly with podSecurityContext.fsGroup: 10001.
#
# The backup key deliberately lives on /data, NOT with the backups: one stolen
# volume should not be both the ciphertext and the key.
RUN useradd --create-home --uid 10001 --user-group radd \
 && mkdir -p /data/attachments /data/models /opt/radd/backups \
 && chown -R radd:radd /data /opt/radd \
 && chmod 700 /opt/radd/backups
EXPOSE 8000


# --- dev: code and SPA arrive as bind mounts; no npm, no baked bundle ---
FROM base AS dev
# Stays root so compose can drop to whatever uid the developer needs (rootless
# podman maps container root -> the host user, so files the container writes —
# alembic revisions, __pycache__ — land owned by you).
CMD ["sh", "-c", "alembic upgrade head && uvicorn --factory radd.app:create_app \
--host 0.0.0.0 --port 8000 --reload --reload-dir /app/server/src"]


# --- production: the built SPA + plugin UI remotes, running unprivileged ---
FROM base AS runtime
COPY --from=web /build/web/dist /app/web/dist
# The built remotes land back where the loader looks for them: the module's own
# ui/dist (registries.plugin_ui_dirs). The .py sources this overwrites are
# byte-identical — both stages copy the same build context.
COPY --from=web /build/server/src/radd/modules /app/server/src/radd/modules
USER radd
VOLUME /data /opt/radd/backups

# Single-node convenience: converge the schema, then serve. Helm runs the
# migration as a pre-upgrade Job instead (see deploy/helm/radd).
CMD ["sh", "-c", "alembic upgrade head && uvicorn --factory radd.app:create_app --host 0.0.0.0 --port 8000"]
