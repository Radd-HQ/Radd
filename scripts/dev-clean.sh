#!/bin/sh
# Start a CLEAN dev instance — empty database, empty storage, everything wired.
#
#   sh scripts/dev-clean.sh          # wipe and rebuild the clean instance
#   sh scripts/dev-clean.sh --keep   # start it again WITHOUT wiping
#
# "Clean" means no data, not no configuration. It comes up with:
#   - an empty database on :5457 and empty Garage volumes on :3920/:3930
#   - both storage hosts registered ("Content" default, "General" selectable)
#     and the routing chain in place — one host cannot exercise spec 102
#   - an optional RADD_SEED_LLM_BASE_URL provider holding the chat + vision roles, TEI holding embeddings
#   - every AI feature toggle on
#   - an admin account to sign in with
#
# It is a SEPARATE database and separate volumes from `scripts/dev.sh`, so
# switching back and forth costs nothing and this can never wipe your real work.
set -e

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${RADD_DEV_PORT:-8000}"
DB_PORT="${RADD_CLEAN_DB_PORT:-5457}"
EMAIL="${RADD_SEED_EMAIL:-hussein@hjarrar.com}"
PASSWORD="${RADD_SEED_PASSWORD:-change-me}"
NAME="${RADD_SEED_NAME:-Hussein Jarrar}"

. "$ROOT/scripts/lib/devstack.sh"

KEEP=0
[ "$1" = "--keep" ] && KEEP=1

say "clean stack"

if [ "$KEEP" -eq 1 ]; then
    step "keeping the existing clean data (--keep)"
else
    # `down -v` removes this project's volumes only. The working stack is a
    # different compose project with different volume names and is untouched.
    step "wiping the clean database and storage"
    podman compose -f compose.clean.yaml down -v >/dev/null 2>&1 || true
fi

step "postgres :$DB_PORT"
podman compose -f compose.clean.yaml up -d db >/dev/null
wait_for_pg "$DB_PORT"

step "garage :3920 / :3930"
podman compose -f compose.clean.yaml up -d garage-1 garage-2 >/dev/null
# Garage needs a moment before its admin socket answers.
sleep 4
for node in garage-1 garage-2; do
    step "garage layout: $node"
    RADD_COMPOSE_FILE=compose.clean.yaml RADD_COMPOSE_PROFILE= \
        sh deploy/garage/init.sh "$node" >/dev/null 2>&1 || {
            printf '     \033[2m(%s init failed — re-run: sh scripts/dev-clean.sh --keep)\033[0m\n' "$node"
        }
done

step "embeddings :8081"
start_embeddings

URL="$(pg_url "$DB_PORT")"

step "migrations"
(cd server && env RADD_DATABASE_URL="$URL" uv run alembic upgrade head >/dev/null)

step "admin account: $EMAIL"
(cd server && env RADD_DATABASE_URL="$URL" uv run python -m radd.seed \
    --email "$EMAIL" --password "$PASSWORD" --name "$NAME" >/dev/null)

step "storage hosts, routing chain, AI providers, feature toggles"
(cd server && env RADD_DATABASE_URL="$URL" \
    RADD_SEED_CONTENT_ENDPOINT="localhost:3920" \
    RADD_SEED_GENERAL_ENDPOINT="localhost:3930" \
    uv run python scripts/seed_dev_stack.py | sed 's/^/     /')

step "web bundle"
build_web

printf '\n  \033[2msign in as %s / %s\033[0m\n' "$EMAIL" "$PASSWORD"
serve "$URL" "$PORT"
