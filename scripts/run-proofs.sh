#!/bin/sh
# Run the real-backend browser proofs against an app this script starts (RADD-1580).
#
#   RADD_PROOF_DATABASE_URL=postgresql+psycopg://radd:radd@127.0.0.1:5432/radd_proofs sh scripts/run-proofs.sh
#
# The database must be an EMPTY throwaway: this migrates it, seeds an admin and
# lets the proofs create and delete projects, teams and users in it. It has its
# own variable name so that it is never the database the dev stack points at.
# Needs the SPA built first (cd web && npm run build:all): the app serves web/dist.
set -eu
: "${RADD_PROOF_DATABASE_URL:?set RADD_PROOF_DATABASE_URL to an empty throwaway database}"
PORT="${RADD_PROOF_PORT:-8030}"
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
EMAIL=proof-admin@example.com
PASSWORD=proof-only-password

export RADD_DATABASE_URL="$RADD_PROOF_DATABASE_URL"
export RADD_APP_BASE_URL="http://127.0.0.1:$PORT"
export RADD_BACKUP_TOOLS_OPTIONAL=true RADD_BACKUP_KEY_FILE="$WORK/key" RADD_BACKUP_DIR="$WORK/backups"
export RADD_ATTACHMENTS_DIR="$WORK/attachments"
# A developer's .env may point at a directory or another tracker; a proof run talks to neither.
export RADD_LDAP_URL= RADD_JIRA_BASE_URL=

cd "$ROOT/server"
uv run alembic upgrade head
uv run python -m radd.seed --email "$EMAIL" --password "$PASSWORD" --name "Proof Admin"
uv run uvicorn --factory radd.app:create_app --host 127.0.0.1 --port "$PORT" > "$WORK/app.log" 2>&1 &
APP=$!
trap 'kill "$APP" 2>/dev/null || true; wait "$APP" 2>/dev/null || true; rm -rf "$WORK"' EXIT

ready=""
for _ in $(seq 1 60); do
  if curl -fsS -m 2 "http://127.0.0.1:$PORT/ready" > /dev/null 2>&1; then ready=yes; break; fi
  sleep 2
done
if [ -z "$ready" ]; then
  echo "the app did not become ready on :$PORT" >&2
  tail -40 "$WORK/app.log" >&2
  exit 1
fi

cd "$ROOT/web"
RADD_PROOF_BASE_URL="http://127.0.0.1:$PORT" RADD_PROOF_EMAIL="$EMAIL" RADD_PROOF_PASSWORD="$PASSWORD" npm run test:proofs
