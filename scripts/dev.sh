#!/bin/sh
# Start the WORKING dev stack — the database you have been building against.
#
#   sh scripts/dev.sh
#
# Brings up Postgres (:5455), the two Garage hosts (:3900/:3910) and the GPU
# embeddings server (:8081), migrates to head, rebuilds the SPA, and runs the
# server on :8000 against your existing data.
#
# Its opposite number is `scripts/dev-clean.sh`, which runs an empty instance on
# a SEPARATE database and separate Garage volumes. Switching between them costs
# nothing and neither can touch the other's data — that is the whole design.
set -e

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${RADD_DEV_PORT:-8000}"

. "$ROOT/scripts/lib/devstack.sh"

say "working stack"

# The working database is compose.yaml's, on 5455 — NOT compose.dev.yaml's 5456.
# Getting that wrong points the server at an empty schema and looks like the data
# vanished.
step "postgres :5455"
podman compose -f compose.yaml up -d db >/dev/null
wait_for_pg 5455

step "garage :3900 / :3910"
podman compose -f compose.dev.yaml --profile storage up -d garage-1 garage-2 >/dev/null

step "embeddings :8081"
start_embeddings

step "migrations"
(cd server && env RADD_DATABASE_URL="$(pg_url 5455)" uv run alembic upgrade head >/dev/null)

step "web bundle"
build_web

serve "$(pg_url 5455)" "$PORT"
