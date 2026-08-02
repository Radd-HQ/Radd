#!/usr/bin/env bash
# Webhook slice demo: a local receiver gets signed deliveries; a dead endpoint shows retries.
# RBAC is on: signs in as the seeded admin first (override with DEMO_EMAIL/DEMO_PASSWORD).
# NOTE (spec 86): this walkthrough predates the workspace eradication — it still
# POSTs /workspaces and threads workspace_id, which the server no longer accepts.
# Run only against a pre-spec-86 build, or update these curls to the global surface.
set -euo pipefail
API=${API:-http://localhost:8000/api/v1}
RUN=$(date +%s)
DEMO_EMAIL=${DEMO_EMAIL:-${RADD_SEED_EMAIL:-hussein@hjarrar.com}}
DEMO_PASSWORD=${DEMO_PASSWORD:-${RADD_SEED_PASSWORD:-change-me}}
SERVER_DIR=$(cd "$(dirname "$0")/.." && pwd)
RECV_PORT=8977
RECV_LOG=$(mktemp)
JAR=$(mktemp)

say()  { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
post() { curl -sS -b "$JAR" -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }
jget() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

python3 - "$RECV_LOG" "$RECV_PORT" <<'PY' &
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

log = open(sys.argv[1], "a")

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["content-length"])).decode()
        json.dump({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}, log)
        log.write("\n"); log.flush()
        self.send_response(200); self.end_headers()
    def log_message(self, *args): pass

HTTPServer(("127.0.0.1", int(sys.argv[2])), Handler).serve_forever()
PY
RECV_PID=$!
trap 'kill $RECV_PID 2>/dev/null; rm -f "$RECV_LOG" "$JAR"' EXIT
sleep 0.5

say "0. Seed + sign in (webhook management is admin-level)"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
curl -sS -c "$JAR" -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$DEMO_EMAIL\",\"password\":\"$DEMO_PASSWORD\"}"
echo "signed in as $DEMO_EMAIL"

say "1. Workspace, project, and a webhook endpoint subscribed to item.created"
WS_ID=$(post /workspaces "{\"name\":\"Hook Demo\",\"slug\":\"hooks-$RUN\"}" | jget "['id']")
P_ID=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"TD\",\"name\":\"TD\"}" | jget "['id']")
EP=$(post /webhooks "{\"workspace_id\":\"$WS_ID\",\"url\":\"http://127.0.0.1:$RECV_PORT/hook\",\"event_types\":[\"item.created\"],\"description\":\"demo receiver\"}")
echo "$EP" | python3 -m json.tool
SECRET=$(echo "$EP" | jget "['secret']")

say "2. Also register a DEAD endpoint (closed port) to show the retry machinery"
EP2_ID=$(post /webhooks "{\"workspace_id\":\"$WS_ID\",\"url\":\"http://127.0.0.1:9/dead\",\"event_types\":[\"item.created\"]}" | jget "['id']")

say "3. Create an item, give the dispatcher a moment"
post /items "{\"project_id\":\"$P_ID\",\"title\":\"webhook demo item\",\"labels\":[\"hooks\"]}" | jget "['key']"
sleep 3

say "4. Receiver got the delivery — verify the Standard Webhooks HMAC signature"
python3 - "$RECV_LOG" "$SECRET" <<'PY'
import base64, hashlib, hmac, json, sys

log_path, secret = sys.argv[1], sys.argv[2]
key = base64.b64decode(secret.removeprefix("whsec_"))
lines = list(open(log_path))
if not lines:
    raise SystemExit("no deliveries received!")
for line in lines:
    request = json.loads(line)
    headers, body = request["headers"], request["body"]
    signed = f"{headers['webhook-id']}.{headers['webhook-timestamp']}.{body}".encode()
    expected = "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    data = json.loads(body)
    valid = hmac.compare_digest(expected, headers["webhook-signature"])
    print(f"type={data['type']}  item={data['data'].get('key')}  signature_valid={valid}")
PY

say "5. The dead endpoint's delivery is scheduled for retry (then dead-letters)"
curl -sS -b "$JAR" "$API/webhooks/$EP2_ID/deliveries" | python3 -c "
import json, sys
for d in json.load(sys.stdin):
    print(f\"status={d['status']}  attempts={d['attempts']}  next_attempt_at={d['next_attempt_at']}  error={d['last_error']}\")"

say "done"
