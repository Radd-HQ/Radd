#!/usr/bin/env bash
# End-to-end tour of the current slices: registry-driven custom fields,
# workflow states as data, labels, epic/issue/subtask hierarchy, assignment,
# comments, action RBAC + field-level visibility, event stream.
# Rerunnable (fresh workspace each run). Signs in as the seeded admin —
# override with DEMO_EMAIL/DEMO_PASSWORD.
# NOTE (spec 86): this walkthrough predates the workspace eradication — it still
# POSTs /workspaces and threads workspace_id, which the server no longer accepts.
# Run only against a pre-spec-86 build, or update these curls to the global surface.
set -euo pipefail
API=${API:-http://localhost:8000/api/v1}
RUN=$(date +%s)
DEMO_EMAIL=${DEMO_EMAIL:-${RADD_SEED_EMAIL:-hussein@hjarrar.com}}
DEMO_PASSWORD=${DEMO_PASSWORD:-${RADD_SEED_PASSWORD:-change-me}}
SERVER_DIR=$(cd "$(dirname "$0")/.." && pwd)
JAR=$(mktemp)         # admin session
DANA_JAR=$(mktemp)    # project member via team
VIEWER_JAR=$(mktemp)  # workspace member -> open-visibility viewer
TRIAGER_JAR=$(mktemp) # direct project member with a custom role
trap 'rm -f "$JAR" "$DANA_JAR" "$VIEWER_JAR" "$TRIAGER_JAR"' EXIT

say()   { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
post()  { curl -sS -b "$JAR" -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }
patch() { curl -sS -b "$JAR" -X PATCH "$API$1" -H 'content-type: application/json' -d "$2"; }
get()   { curl -sS -b "$JAR" "$API$1"; }
pp()    { python3 -m json.tool; }
jget()  { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
login() { # login <jar> <email> <password>
  curl -sS -c "$1" -X POST "$API/auth/login" -H 'content-type: application/json' \
    -d "{\"email\":\"$2\",\"password\":\"$3\"}"
}

say "0. RBAC is on: anonymous requests get 401 — seed and sign in first"
echo "GET /items anonymous -> HTTP $(curl -sS -o /dev/null -w '%{http_code}' "$API/items")"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
login "$JAR" "$DEMO_EMAIL" "$DEMO_PASSWORD"
ADMIN_ID=$(get /auth/me | jget "['id']")
echo "signed in as $DEMO_EMAIL ($ADMIN_ID)"

say "1. Create workspace + project TD"
WS_ID=$(post /workspaces "{\"name\":\"Demo Studio\",\"slug\":\"demo-$RUN\"}" | jget "['id']")
PROJECT=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"TD\",\"name\":\"TD Support\"}")
echo "$PROJECT" | pp
P_ID=$(echo "$PROJECT" | jget "['id']")

say "2. Default workflow was seeded transactionally with the project (hook)"
get "/states?project_id=$P_ID" | python3 -c "
import json, sys
for s in json.load(sys.stdin):
    default = '  <- default for new items' if s['is_default'] else ''
    print(f\"{s['position']:>2}. {s['name']:<14} [{s['category']}]{default}\")"

say "3. Define custom fields via API (no code, no restart)"
post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"show\",\"name\":\"Show\",\"type\":\"select\",\"options\":[\"RUX\",\"BNX\",\"G64\",\"ALL_SHOWS\"]}" > /dev/null
post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"department\",\"name\":\"Department\",\"type\":\"select\",\"required\":true,\"options\":[\"FX\",\"Pipeline\",\"Lighting\",\"Assets\"]}" > /dev/null
post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"software\",\"name\":\"Software\",\"type\":\"multi_select\",\"options\":[\"Maya\",\"Houdini\",\"Nuke\"]}" > /dev/null
echo "created: show [select], department [required select], software [multi_select]"

say "4. Create an item — validated custom fields + auto-created labels, all inline"
ITEM=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"rnd sequence shots not showing in asset loader\",\"priority\":\"high\",\"labels\":[\"houdini\",\"farm\"],\"custom_fields\":{\"show\":\"RUX\",\"department\":\"Pipeline\",\"software\":[\"Maya\"]}}")
echo "$ITEM" | pp
ITEM_ID=$(echo "$ITEM" | jget "['id']")

say "5. Registry rejects bad values (unknown option / missing required)"
post /items "{\"project_id\":\"$P_ID\",\"title\":\"bad\",\"custom_fields\":{\"show\":\"NOPE\"}}" | pp

say "6. Add a custom state and move the item into it"
STATE_ID=$(post /states "{\"project_id\":\"$P_ID\",\"name\":\"Under Investigation\",\"category\":\"in_progress\"}" | jget "['id']")
patch "/items/$ITEM_ID" \
  "{\"state_id\":\"$STATE_ID\",\"labels\":[\"houdini\",\"farm\",\"urgent\"],\"custom_fields\":{\"show\":\"BNX\",\"software\":null}}" | pp

say "7. Filter the board the way a UI would (category=in_progress)"
get "/items?project_id=$P_ID&category=in_progress" | python3 -c "
import json, sys
for i in json.load(sys.stdin):
    print(f\"{i['key']:<8} {i['state']['name']:<20} {','.join(i['labels']):<24} {i['title']}\")"

say "8. Set up a demo user + team; attaching the team grants the 'member' role"
USER_ID=$(post /users "{\"email\":\"dana-$RUN@example.com\",\"name\":\"Dana Demo\",\"password\":\"demo-pass-123\"}" | jget "['id']")
TEAM_ID=$(post /teams "{\"workspace_id\":\"$WS_ID\",\"name\":\"Pipeline Crew\"}" | jget "['id']")
post "/teams/$TEAM_ID/members" "{\"user_id\":\"$USER_ID\"}" > /dev/null
post "/projects/$P_ID/teams" "{\"team_id\":\"$TEAM_ID\",\"role\":\"member\"}" > /dev/null
echo "user 'Dana Demo' ($USER_ID) is on team 'Pipeline Crew' ($TEAM_ID), attached to TD as member"

say "9. Hierarchy: epic -> issue (assigned to Dana + Pipeline Crew) -> subtask"
EPIC_ID=$(post /items "{\"project_id\":\"$P_ID\",\"kind\":\"epic\",\"title\":\"Asset loader revamp\",\"custom_fields\":{\"department\":\"Pipeline\"}}" | jget "['id']")
ISSUE=$(post /items "{\"project_id\":\"$P_ID\",\"kind\":\"issue\",\"parent_id\":\"$EPIC_ID\",\"assignee_id\":\"$USER_ID\",\"team_id\":\"$TEAM_ID\",\"title\":\"Cache ignores sequence revision\",\"priority\":\"high\",\"custom_fields\":{\"department\":\"Pipeline\"}}")
ISSUE_ID=$(echo "$ISSUE" | jget "['id']")
post /items "{\"project_id\":\"$P_ID\",\"kind\":\"subtask\",\"parent_id\":\"$ISSUE_ID\",\"title\":\"Bust cache on revision bump\",\"custom_fields\":{\"department\":\"Pipeline\"}}" > /dev/null
echo "$ISSUE" | python3 -c "
import json, sys
i = json.load(sys.stdin)
print(f\"{i['key']} [{i['kind']}] {i['title']}\")
print(f\"  parent   -> {i['parent']['key']} {i['parent']['title']}\")
print(f\"  assignee -> {i['assignee']['name']}   team -> {i['team']['name']}\")"

say "10. Comments: the authenticated actor is the author (Dana signs in herself)"
login "$DANA_JAR" "dana-$RUN@example.com" "demo-pass-123"
curl -sS -b "$DANA_JAR" -X POST "$API/items/$ISSUE_ID/comments" -H 'content-type: application/json' \
  -d "{\"body\":\"Repro'd on the farm - the cache key drops the sequence revision.\"}" > /dev/null
post "/items/$ISSUE_ID/comments" "{\"body\":\"Nice catch, fold the fix into the loader revamp epic.\"}" > /dev/null
get "/items/$ISSUE_ID/comments" | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    print(f\"[{c['created_at'][:19]}] {c['author']['name']}: {c['body']}\")"

say "11. The epic board view: ?kind=epic with live child/comment counts"
get "/items?project_id=$P_ID&kind=epic" | python3 -c "
import json, sys
for i in json.load(sys.stdin):
    print(f\"{i['key']:<8} [{i['kind']}] children={i['child_count']} comments={i['comment_count']}  {i['title']}\")"
get "/items/$ISSUE_ID" | python3 -c "
import json, sys
i = json.load(sys.stdin)
print(f\"{i['key']:<8} [{i['kind']}] children={i['child_count']} comments={i['comment_count']}  {i['title']}\")"

say "12. Hierarchy rules are enforced (subtask under an epic -> 409)"
post /items "{\"project_id\":\"$P_ID\",\"kind\":\"subtask\",\"parent_id\":\"$EPIC_ID\",\"title\":\"bad nesting\",\"custom_fields\":{\"department\":\"Pipeline\"}}" | pp

say "13. Field-level visibility: budget_ms readable/writable only by the builtin admin ROLE (spec 07 grants)"
BUDGET_FIELD_ID=$(post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"budget_ms\",\"name\":\"Budget\",\"type\":\"number\"}" | jget "['id']")
ADMIN_ROLE_ID=$(get "/roles?workspace_id=$WS_ID" | python3 -c "
import json,sys; print(next(r['id'] for r in json.load(sys.stdin) if r['key']=='admin'))")
curl -sS -b "$JAR" -X PUT "$API/fields/$BUDGET_FIELD_ID/permissions" -H 'content-type: application/json' \
  -d "[{\"subject_type\":\"role\",\"subject_id\":\"$ADMIN_ROLE_ID\",\"access\":\"read\"},{\"subject_type\":\"role\",\"subject_id\":\"$ADMIN_ROLE_ID\",\"access\":\"write\"}]" > /dev/null
patch "/items/$ITEM_ID" "{\"custom_fields\":{\"budget_ms\":42}}" > /dev/null
VIEWER_EMAIL="viewer-$RUN@example.com"
VIEWER_ID=$(post /users "{\"email\":\"$VIEWER_EMAIL\",\"name\":\"Vera Viewer\",\"password\":\"viewer-pass-123\"}" | jget "['id']")
post "/workspaces/$WS_ID/members" "{\"user_id\":\"$VIEWER_ID\",\"role\":\"member\"}" > /dev/null
login "$VIEWER_JAR" "$VIEWER_EMAIL" "viewer-pass-123"
echo "workspace member 'Vera Viewer' -> effective role on TD: viewer (open visibility)"
echo
echo "admin  GET custom_fields:  $(get "/items/$ITEM_ID" | jget "['custom_fields']")"
echo "viewer GET custom_fields:  $(curl -sS -b "$VIEWER_JAR" "$API/items/$ITEM_ID" | jget "['custom_fields']")   <- budget_ms filtered out"
echo
echo "viewer tries to write the field:"
curl -sS -b "$VIEWER_JAR" -X PATCH "$API/items/$ITEM_ID" -H 'content-type: application/json' \
  -d '{"custom_fields":{"budget_ms":1}}' -w '  -> HTTP %{http_code}\n'
echo "viewer tries to create an item:"
curl -sS -b "$VIEWER_JAR" -X POST "$API/items" -H 'content-type: application/json' \
  -d "{\"project_id\":\"$P_ID\",\"title\":\"nope\",\"custom_fields\":{\"department\":\"FX\"}}" -w '  -> HTTP %{http_code}\n'

say "14. The fields are live in OpenAPI automatically (restricted ones flagged)"
curl -sS "${API%/api/v1}/openapi.json" | python3 -c "
import json, sys
schemas = json.load(sys.stdin)['components']['schemas']
props = schemas['ItemRead']['properties']['custom_fields']['properties']
for key, schema in props.items():
    kind = schema.get('type', '?')
    opts = schema.get('enum') or (schema.get('items') or {}).get('enum') or ''
    req = ' (required)' if schema.get('x-required') else ''
    restricted = 'x-restricted' if schema.get('x-restricted') else 'open'
    print(f'{key:<14} {kind:<8} {restricted:<14} {opts}{req}')"

say "15. Everything is on the event stream, with the acting user (workspace-scoped tail)"
COOKIE="radd_session=$(awk '$6=="radd_session" {print $7}' "$JAR" | tail -1)"
python3 - "$API" "$WS_ID" "$COOKIE" <<'PY'
import json, sys, urllib.request
api, ws, cookie, after = sys.argv[1], sys.argv[2], sys.argv[3], 0
while True:  # page the whole stream; print only this run's workspace
    request = urllib.request.Request(f"{api}/events?after={after}&limit=500", headers={"Cookie": cookie})
    with urllib.request.urlopen(request) as response:
        page = json.load(response)
    if not page:
        break
    for e in page:
        if e["workspace_id"] == ws:
            actor = (e["actor_id"] or "-")[:8]
            print(f"{e['id']:>4}  actor={actor:<8}  {e['event_type']:<20} {e['entity_type']:<10} {e['entity_id']}")
    after = page[-1]["id"]
PY

say "16. Roles are data: custom role 'triager' updates items but cannot create (spec 06)"
TRIAGER_ROLE_ID=$(post /roles "{\"workspace_id\":\"$WS_ID\",\"key\":\"triager\",\"name\":\"Triager\",\"description\":\"Can triage existing items\",\"permissions\":[\"item.read\",\"item.update\",\"comment.write\"]}" | jget "['id']")
get "/roles?workspace_id=$WS_ID" | python3 -c "
import json, sys
for r in json.load(sys.stdin):
    kind = 'builtin' if r['is_builtin'] else 'custom '
    print(f\"{r['position']:>2}. {r['key']:<8} [{kind}] {', '.join(r['permissions'])}\")"
TRIAGER_EMAIL="tariq-$RUN@example.com"
TRIAGER_ID=$(post /users "{\"email\":\"$TRIAGER_EMAIL\",\"name\":\"Tariq Triager\",\"password\":\"triager-pass-123\"}" | jget "['id']")
post "/workspaces/$WS_ID/members" "{\"user_id\":\"$TRIAGER_ID\",\"role\":\"member\"}" > /dev/null
echo "direct project membership (no team needed):"
post "/projects/$P_ID/members" "{\"user_id\":\"$TRIAGER_ID\",\"role_id\":\"$TRIAGER_ROLE_ID\"}" | pp
login "$TRIAGER_JAR" "$TRIAGER_EMAIL" "triager-pass-123"
echo
echo "triager PATCHes an item (item.update granted):"
curl -sS -b "$TRIAGER_JAR" -X PATCH "$API/items/$ITEM_ID" -H 'content-type: application/json' \
  -d '{"title":"rnd sequence shots not showing in asset loader (triaged)"}' -o /dev/null -w '  -> HTTP %{http_code}\n'
echo "triager tries to CREATE an item (item.create not granted):"
curl -sS -b "$TRIAGER_JAR" -X POST "$API/items" -H 'content-type: application/json' \
  -d "{\"project_id\":\"$P_ID\",\"title\":\"nope\",\"custom_fields\":{\"department\":\"FX\"}}" -w '  -> HTTP %{http_code}\n'
echo
echo "ProjectRead.permissions for the triager (direct role UNION workspace-member floor):"
curl -sS -b "$TRIAGER_JAR" "$API/projects?workspace_id=$WS_ID" | python3 -c "
import json, sys
for p in json.load(sys.stdin):
    print(f\"  {p['key']:<4} {sorted(p['permissions'])}\")"

say "done — explore at ${API%/api/v1}/docs"
