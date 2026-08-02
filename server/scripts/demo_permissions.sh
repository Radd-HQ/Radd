#!/usr/bin/env bash
# Field-permission grants + internal comments (spec 07): per-role/team read|write
# grants on custom fields (default-open when a field has no rows), PUT full-list
# replace under project.manage, x-restricted in OpenAPI, and comment visibility
# (public|internal) gated by comment.read_internal — including visible-only
# comment_count. Rerunnable (fresh workspace each run). Signs in as the seeded
# admin — override with DEMO_EMAIL/DEMO_PASSWORD.
# NOTE (spec 86): this walkthrough predates the workspace eradication — it still
# POSTs /workspaces and threads workspace_id, which the server no longer accepts.
# Run only against a pre-spec-86 build, or update these curls to the global surface.
set -euo pipefail
API=${API:-http://localhost:8000/api/v1}
RUN=$(date +%s)
DEMO_EMAIL=${DEMO_EMAIL:-${RADD_SEED_EMAIL:-hussein@hjarrar.com}}
DEMO_PASSWORD=${DEMO_PASSWORD:-${RADD_SEED_PASSWORD:-change-me}}
SERVER_DIR=$(cd "$(dirname "$0")/.." && pwd)
JAR=$(mktemp)       # admin session
LENA_JAR=$(mktemp)  # "Leads" team member (team-granted field read+write)
MIRA_JAR=$(mktemp)  # direct project member, builtin member role
TARIQ_JAR=$(mktemp) # custom "triager" role: item.update but NOT the write-granted role
FINN_JAR=$(mktemp)  # custom "contractor" role: comment.write but no comment.read_internal
VERA_JAR=$(mktemp)  # plain workspace member -> viewer floor
trap 'rm -f "$JAR" "$LENA_JAR" "$MIRA_JAR" "$TARIQ_JAR" "$FINN_JAR" "$VERA_JAR"' EXIT

say()   { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
post()  { curl -sS -b "$JAR" -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }
put()   { curl -sS -b "$JAR" -X PUT "$API$1" -H 'content-type: application/json' -d "$2"; }
patch() { curl -sS -b "$JAR" -X PATCH "$API$1" -H 'content-type: application/json' -d "$2"; }
get()   { curl -sS -b "$JAR" "$API$1"; }
jget()  { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
login() { # login <jar> <email> <password>
  curl -sS -c "$1" -X POST "$API/auth/login" -H 'content-type: application/json' \
    -d "{\"email\":\"$2\",\"password\":\"$3\"}"
}
mkuser() { # mkuser <jar> <slug> <name> -> user id on stdout
  local id
  id=$(post /users "{\"email\":\"$2-$RUN@example.com\",\"name\":\"$3\",\"password\":\"$2-pass-123\"}" | jget "['id']")
  post "/workspaces/$WS_ID/members" "{\"user_id\":\"$id\",\"role\":\"member\"}" > /dev/null
  login "$1" "$2-$RUN@example.com" "$2-pass-123"
  echo "$id"
}
expect_code() { # expect_code <label> <expected> <curl args...>
  local label=$1 expected=$2; shift 2
  local got
  got=$(curl -sS -o /dev/null -w '%{http_code}' "$@")
  if [ "$got" = "$expected" ]; then echo "OK   $label -> HTTP $got"
  else echo "FAIL $label -> HTTP $got (expected $expected)"; exit 1; fi
}
check() { # check <label> <python expr over json stdin>
  python3 -c "
import json, sys
data = json.load(sys.stdin)
ok = bool($2)
print(('OK  ' if ok else 'FAIL') + ' $1')
sys.exit(0 if ok else 1)"
}

say "0. Seed + sign in"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
login "$JAR" "$DEMO_EMAIL" "$DEMO_PASSWORD"
echo "signed in as $DEMO_EMAIL"

say "1. Fresh workspace + project GR; the cast (team, builtin + custom roles)"
WS_ID=$(post /workspaces "{\"name\":\"Grants Demo\",\"slug\":\"perm-$RUN\"}" | jget "['id']")
P_ID=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"GR\",\"name\":\"Grants\"}" | jget "['id']")
MEMBER_ROLE_ID=$(get "/roles?workspace_id=$WS_ID" | python3 -c "
import json,sys; print(next(r['id'] for r in json.load(sys.stdin) if r['key']=='member'))")
TRIAGER_ROLE_ID=$(post /roles "{\"workspace_id\":\"$WS_ID\",\"key\":\"triager\",\"name\":\"Triager\",\"permissions\":[\"item.read\",\"item.update\",\"comment.write\"]}" | jget "['id']")
CONTRACTOR_ROLE_ID=$(post /roles "{\"workspace_id\":\"$WS_ID\",\"key\":\"contractor\",\"name\":\"Contractor\",\"permissions\":[\"item.read\",\"comment.write\"]}" | jget "['id']")
LENA_ID=$(mkuser "$LENA_JAR" lena "Lena Lead")
MIRA_ID=$(mkuser "$MIRA_JAR" mira "Mira Member")
TARIQ_ID=$(mkuser "$TARIQ_JAR" tariq "Tariq Triager")
FINN_ID=$(mkuser "$FINN_JAR" finn "Finn Freelance")
VERA_ID=$(mkuser "$VERA_JAR" vera "Vera Viewer")
TEAM_ID=$(post /teams "{\"workspace_id\":\"$WS_ID\",\"name\":\"Leads\"}" | jget "['id']")
post "/teams/$TEAM_ID/members" "{\"user_id\":\"$LENA_ID\"}" > /dev/null
post "/projects/$P_ID/teams" "{\"team_id\":\"$TEAM_ID\",\"role\":\"member\"}" > /dev/null
post "/projects/$P_ID/members" "{\"user_id\":\"$MIRA_ID\",\"role_id\":\"$MEMBER_ROLE_ID\"}" > /dev/null
post "/projects/$P_ID/members" "{\"user_id\":\"$TARIQ_ID\",\"role_id\":\"$TRIAGER_ROLE_ID\"}" > /dev/null
post "/projects/$P_ID/members" "{\"user_id\":\"$FINN_ID\",\"role_id\":\"$CONTRACTOR_ROLE_ID\"}" > /dev/null
echo "lena: on team 'Leads' (member role) | mira: member | tariq: triager | finn: contractor | vera: floor viewer"

say "2. Fields: budget read+write granted ONLY to team Leads; estimate write granted to the member ROLE"
BUDGET_ID=$(post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"budget\",\"name\":\"Budget\",\"type\":\"number\"}" | jget "['id']")
EST_ID=$(post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"estimate\",\"name\":\"Estimate\",\"type\":\"number\"}" | jget "['id']")
put "/fields/$BUDGET_ID/permissions" "[
  {\"subject_type\":\"team\",\"subject_id\":\"$TEAM_ID\",\"access\":\"read\"},
  {\"subject_type\":\"team\",\"subject_id\":\"$TEAM_ID\",\"access\":\"write\"}]" \
  | check "PUT budget grants (team read+write) reflected in FieldDefinitionRead.permissions" "len(data['permissions']) == 2"
put "/fields/$EST_ID/permissions" "[
  {\"subject_type\":\"role\",\"subject_id\":\"$MEMBER_ROLE_ID\",\"access\":\"write\"}]" \
  | check "PUT estimate grants (member-role write)" "data['permissions'][0]['access'] == 'write'"
expect_code "mira (no project.manage) PUT grants" 403 -b "$MIRA_JAR" -X PUT "$API/fields/$BUDGET_ID/permissions" \
  -H 'content-type: application/json' -d '[]'
expect_code "grant to a subject outside the workspace" 409 -b "$JAR" -X PUT "$API/fields/$BUDGET_ID/permissions" \
  -H 'content-type: application/json' -d '[{"subject_type":"role","subject_id":"00000000-0000-0000-0000-000000000001","access":"read"}]'

say "3. Team-granted READ: lena sees budget, mira/vera don't (estimate is read-open for all)"
ITEM_ID=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"Fix the render farm\",\"custom_fields\":{\"budget\":5000,\"estimate\":8}}" | jget "['id']")
curl -sS -b "$LENA_JAR" "$API/items/$ITEM_ID" | check "lena (Leads) sees budget" "data['custom_fields'].get('budget') == 5000"
curl -sS -b "$MIRA_JAR" "$API/items/$ITEM_ID" | check "mira does NOT see budget" "'budget' not in data['custom_fields']"
curl -sS -b "$MIRA_JAR" "$API/items/$ITEM_ID" | check "mira still sees estimate (no read rows -> open)" "data['custom_fields'].get('estimate') == 8"
curl -sS -b "$VERA_JAR" "$API/items/$ITEM_ID" | check "vera (floor viewer) does NOT see budget" "'budget' not in data['custom_fields']"
curl -sS -b "$JAR" "$API/items/$ITEM_ID" | check "admin (project.manage) sees budget" "data['custom_fields'].get('budget') == 5000"
curl -sS -b "$MIRA_JAR" "$API/items?project_id=$P_ID" | check "list responses filter budget too" "all('budget' not in i['custom_fields'] for i in data)"

say "4. Writes: team grant vs role grant vs 403"
expect_code "lena writes budget (team write grant)" 200 -b "$LENA_JAR" -X PATCH "$API/items/$ITEM_ID" \
  -H 'content-type: application/json' -d '{"custom_fields":{"budget":6000}}'
expect_code "mira writes budget" 403 -b "$MIRA_JAR" -X PATCH "$API/items/$ITEM_ID" \
  -H 'content-type: application/json' -d '{"custom_fields":{"budget":1}}'
expect_code "mira writes estimate (member-role write grant)" 200 -b "$MIRA_JAR" -X PATCH "$API/items/$ITEM_ID" \
  -H 'content-type: application/json' -d '{"custom_fields":{"estimate":13}}'
expect_code "tariq (item.update but not the granted role) writes estimate" 403 -b "$TARIQ_JAR" -X PATCH "$API/items/$ITEM_ID" \
  -H 'content-type: application/json' -d '{"custom_fields":{"estimate":2}}'
expect_code "tariq edits the title (plain item.update still fine)" 200 -b "$TARIQ_JAR" -X PATCH "$API/items/$ITEM_ID" \
  -H 'content-type: application/json' -d '{"title":"Fix the render farm (triaged)"}'
curl -sS -b "$TARIQ_JAR" "$API/items/$ITEM_ID" | check "tariq READS estimate (write-gated, read-open)" "data['custom_fields'].get('estimate') == 13"

say "5. Restricted fields are flagged in OpenAPI (x-restricted, no grant details)"
curl -sS "${API%/api/v1}/openapi.json" | check "budget + estimate x-restricted, open fields unflagged" "
data['components']['schemas']['ItemRead']['properties']['custom_fields']['properties']['budget'].get('x-restricted') is True
and data['components']['schemas']['ItemRead']['properties']['custom_fields']['properties']['estimate'].get('x-restricted') is True"

say "6. Internal comments: creation gated by comment.read_internal"
post "/items/$ITEM_ID/comments" '{"body":"Kickoff notes for everyone.","visibility":"public"}' > /dev/null
post "/items/$ITEM_ID/comments" '{"body":"Internal: vendor quote is inflated.","visibility":"internal"}' > /dev/null
curl -sS -b "$MIRA_JAR" -X POST "$API/items/$ITEM_ID/comments" -H 'content-type: application/json' \
  -d '{"body":"Internal from mira: agreed, push back.","visibility":"internal"}' \
  | check "mira (member: has comment.read_internal) posts internal" "data['visibility'] == 'internal'"
expect_code "finn (contractor: comment.write only) posts internal" 403 -b "$FINN_JAR" -X POST "$API/items/$ITEM_ID/comments" \
  -H 'content-type: application/json' -d '{"body":"sneaky","visibility":"internal"}'
FINN_COMMENT_ID=$(curl -sS -b "$FINN_JAR" -X POST "$API/items/$ITEM_ID/comments" -H 'content-type: application/json' \
  -d '{"body":"Public from finn.","visibility":"public"}' | jget "['id']")
echo "OK   finn posts public instead ($FINN_COMMENT_ID)"

say "7. Reads filter internal comments; comment_count is visible-only"
curl -sS -b "$MIRA_JAR" "$API/items/$ITEM_ID/comments" | check "mira lists all 4 (2 public + 2 internal)" "
len(data) == 4 and sum(c['visibility'] == 'internal' for c in data) == 2"
curl -sS -b "$FINN_JAR" "$API/items/$ITEM_ID/comments" | check "finn lists only the 2 public" "
len(data) == 2 and all(c['visibility'] == 'public' for c in data)"
curl -sS -b "$VERA_JAR" "$API/items/$ITEM_ID/comments" | check "vera (floor viewer) lists only the 2 public" "
len(data) == 2 and all(c['visibility'] == 'public' for c in data)"
curl -sS -b "$MIRA_JAR" "$API/items/$ITEM_ID" | check "comment_count for mira = 4" "data['comment_count'] == 4"
curl -sS -b "$FINN_JAR" "$API/items/$ITEM_ID" | check "comment_count for finn = 2 (internal excluded)" "data['comment_count'] == 2"
curl -sS -b "$VERA_JAR" "$API/items/$ITEM_ID" | check "comment_count for vera = 2" "data['comment_count'] == 2"

say "8. Edit/delete keep the author-or-admin rule; internal needs the permission on top"
MIRA_INTERNAL_ID=$(curl -sS -b "$MIRA_JAR" "$API/items/$ITEM_ID/comments" | python3 -c "
import json,sys; print(next(c['id'] for c in json.load(sys.stdin) if c['visibility']=='internal' and 'mira' in c['body']))")
expect_code "mira edits her own internal comment" 200 -b "$MIRA_JAR" -X PATCH "$API/comments/$MIRA_INTERNAL_ID" \
  -H 'content-type: application/json' -d '{"body":"Internal from mira: agreed, push back (edited)."}'
expect_code "finn edits his own public comment" 200 -b "$FINN_JAR" -X PATCH "$API/comments/$FINN_COMMENT_ID" \
  -H 'content-type: application/json' -d '{"body":"Public from finn (edited)."}'
expect_code "finn edits mira's internal comment" 403 -b "$FINN_JAR" -X PATCH "$API/comments/$MIRA_INTERNAL_ID" \
  -H 'content-type: application/json' -d '{"body":"nope"}'
expect_code "finn deletes mira's internal comment" 403 -b "$FINN_JAR" -X DELETE "$API/comments/$MIRA_INTERNAL_ID"
expect_code "admin deletes mira's internal comment (project.manage + read_internal)" 204 \
  -b "$JAR" -X DELETE "$API/comments/$MIRA_INTERNAL_ID"

say "all green"
