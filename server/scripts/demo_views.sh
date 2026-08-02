#!/usr/bin/env bash
# Saved views v2 + SLQ (spec 10): views store an SLQ query whose query_string
# round-trips verbatim into GET /items?q=…, with exact-set and exact-order
# assertions; parse errors carry {detail, position}; group_by/swimlane_by axis
# tokens are validated (select-type cf only, must differ). Rerunnable (fresh
# workspace each run). Signs in as the seeded admin — override with
# DEMO_EMAIL/DEMO_PASSWORD.
# NOTE (spec 86): this walkthrough predates the workspace eradication — it still
# POSTs /workspaces and threads workspace_id, which the server no longer accepts.
# Run only against a pre-spec-86 build, or update these curls to the global surface.
set -euo pipefail
API=${API:-http://localhost:8000/api/v1}
RUN=$(date +%s)
DEMO_EMAIL=${DEMO_EMAIL:-${RADD_SEED_EMAIL:-hussein@hjarrar.com}}
DEMO_PASSWORD=${DEMO_PASSWORD:-${RADD_SEED_PASSWORD:-change-me}}
SERVER_DIR=$(cd "$(dirname "$0")/.." && pwd)
JAR=$(mktemp)     # admin session
VIK_JAR=$(mktemp) # plain workspace member
trap 'rm -f "$JAR" "$VIK_JAR"' EXIT

say()   { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
post()  { curl -sS -b "$JAR" -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }
patch() { curl -sS -b "$JAR" -X PATCH "$API$1" -H 'content-type: application/json' -d "$2"; }
get()   { curl -sS -b "$JAR" "$API$1"; }
qget()  { curl -sS -b "$JAR" -G "$API/items" --data-urlencode "project_id=$P_ID" --data-urlencode "q=$1"; }
pp()    { python3 -m json.tool; }
jget()  { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
login() { # login <jar> <email> <password>
  curl -sS -c "$1" -X POST "$API/auth/login" -H 'content-type: application/json' \
    -d "{\"email\":\"$2\",\"password\":\"$3\"}"
}
expect() { # expect <label> <expected-comma-separated-item-keys>  (json list on stdin; any order)
  python3 -c "
import json, sys
expected = sorted(x for x in sys.argv[2].split(',') if x)
got = sorted(i['key'] for i in json.load(sys.stdin))
ok = got == expected
print(('OK  ' if ok else 'FAIL') + f' {sys.argv[1]}: {got}' + ('' if ok else f' != expected {expected}'))
sys.exit(0 if ok else 1)" "$1" "$2"
}
expect_order() { # expect_order <label> <expected-comma-separated-item-keys IN ORDER>
  python3 -c "
import json, sys
expected = [x for x in sys.argv[2].split(',') if x]
got = [i['key'] for i in json.load(sys.stdin)]
ok = got == expected
print(('OK  ' if ok else 'FAIL') + f' {sys.argv[1]}: {got}' + ('' if ok else f' != expected {expected}'))
sys.exit(0 if ok else 1)" "$1" "$2"
}
expect_slq_422() { # expect_slq_422 <label> <bad-slq> <expected-position>
  curl -sS -o /tmp/slq_err.$$ -w '%{http_code}' -b "$JAR" -G "$API/items" \
    --data-urlencode "project_id=$P_ID" --data-urlencode "q=$2" > /tmp/slq_code.$$
  python3 -c "
import json, sys
code = open('/tmp/slq_code.$$').read().strip()
body = json.load(open('/tmp/slq_err.$$'))
assert code == '422', f'expected 422, got {code}'
assert body['position'] == int(sys.argv[2]), f\"position {body['position']} != {sys.argv[2]}\"
print(f'OK   {sys.argv[1]}: 422 position={body[\"position\"]} detail={body[\"detail\"]!r}')" "$1" "$3"
  rm -f /tmp/slq_err.$$ /tmp/slq_code.$$
}

say "0. Seed + sign in"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
login "$JAR" "$DEMO_EMAIL" "$DEMO_PASSWORD"
echo "signed in as $DEMO_EMAIL"

say "1. Fresh workspace + project FX; cf: show[select] software[multi_select] budget[number]"
WS_ID=$(post /workspaces "{\"name\":\"Views Demo\",\"slug\":\"views-$RUN\"}" | jget "['id']")
P_ID=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"FX\",\"name\":\"FX Support\"}" | jget "['id']")
post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"show\",\"name\":\"Show\",\"type\":\"select\",\"options\":[\"RUX\",\"BNX\",\"G64\"]}" > /dev/null
post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"software\",\"name\":\"Software\",\"type\":\"multi_select\",\"options\":[\"Maya\",\"Houdini\",\"Nuke\"]}" > /dev/null
post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"budget\",\"name\":\"Budget\",\"type\":\"number\"}" > /dev/null
IN_PROGRESS=$(get "/states?project_id=$P_ID" | python3 -c "
import json,sys; print(next(s['id'] for s in json.load(sys.stdin) if s['name']=='In Progress'))")
DONE=$(get "/states?project_id=$P_ID" | python3 -c "
import json,sys; print(next(s['id'] for s in json.load(sys.stdin) if s['name']=='Done'))")
ADMIN_ID=$(get /auth/me | jget "['id']")
echo "project FX ($P_ID) ready"

say "2. Items FX-1..FX-7 spanning states/labels/cf/assignee"
A=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"Fire sim cache explodes\",\"priority\":\"blocker\",\"labels\":[\"urgent\",\"fx\"],\"custom_fields\":{\"show\":\"RUX\",\"software\":[\"Houdini\",\"Maya\"]}}" | jget "['id']")
patch "/items/$A" "{\"state_id\":\"$IN_PROGRESS\"}" > /dev/null                        # FX-1 urgent RUX, In Progress
post /items "{\"project_id\":\"$P_ID\",\"title\":\"Comp renders too dark\",\"priority\":\"high\",\"labels\":[\"urgent\"],\"custom_fields\":{\"show\":\"RUX\"}}" > /dev/null   # FX-2 urgent RUX, Triage
post /items "{\"project_id\":\"$P_ID\",\"title\":\"Roto cleanup\",\"labels\":[\"urgent\"],\"custom_fields\":{\"show\":\"BNX\"}}" > /dev/null                                  # FX-3 urgent, other show
post /items "{\"project_id\":\"$P_ID\",\"title\":\"Layout pass\",\"labels\":[\"fx\"],\"custom_fields\":{\"show\":\"RUX\"}}" > /dev/null                                        # FX-4 RUX, no urgent
post /items "{\"project_id\":\"$P_ID\",\"title\":\"Lens distortion plates\",\"assignee_id\":\"$ADMIN_ID\",\"labels\":[\"urgent\"],\"custom_fields\":{\"show\":\"RUX\"}}" > /dev/null  # FX-5 urgent RUX, assigned
post /items "{\"project_id\":\"$P_ID\",\"title\":\"Nuke comp pass\",\"custom_fields\":{\"software\":[\"Nuke\"]}}" > /dev/null                                                  # FX-6 Nuke only
G=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"Fixed lens flare\",\"labels\":[\"urgent\"],\"custom_fields\":{\"show\":\"RUX\"}}" | jget "['id']")
patch "/items/$G" "{\"state_id\":\"$DONE\"}" > /dev/null                              # FX-7 urgent RUX but Done
echo "created FX-1..FX-7 (FX-1 In Progress, FX-7 Done, rest Triage)"

say "3. Shared board view over SLQ, grouped by state with cf.show swimlanes"
SHARED_Q="label = urgent AND show = RUX AND category IN (triage, in_progress)"
SHARED_VIEW=$(post /views "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"FX urgent\",\"view_type\":\"board\",\"shared\":true,\"group_by\":\"state\",\"swimlane_by\":\"cf.show\",\"query\":\"$SHARED_Q\"}")
echo "$SHARED_VIEW" | pp
SHARED_ID=$(echo "$SHARED_VIEW" | jget "['id']")
SHARED_QS=$(echo "$SHARED_VIEW" | jget "['query_string']")
echo "$SHARED_VIEW" | python3 -c "
import json, sys
view = json.load(sys.stdin)
assert view['query'] == '$SHARED_Q', f'query mangled: {view[\"query\"]!r}'
assert view['group_by'] == 'state' and view['swimlane_by'] == 'cf.show'
print('OK   stored query round-trips verbatim; axes stored')"

say "4. The view's query_string composes GET /items with ZERO translation logic"
echo "GET /items?$SHARED_QS"
get "/items?$SHARED_QS" | expect "shared view round-trip" "FX-1,FX-2,FX-5"
echo "   (FX-3 wrong show, FX-4 no urgent label, FX-7 done -> excluded)"

say "5. Personal list view (assignee = none) — private to the admin"
PERSONAL_VIEW=$(post /views "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"My focus: unassigned RUX\",\"view_type\":\"list\",\"query\":\"assignee = none AND show = RUX\"}")
PERSONAL_ID=$(echo "$PERSONAL_VIEW" | jget "['id']")
PERSONAL_QS=$(echo "$PERSONAL_VIEW" | jget "['query_string']")
echo "GET /items?$PERSONAL_QS"
get "/items?$PERSONAL_QS" | expect "personal view round-trip" "FX-1,FX-2,FX-4,FX-7"
echo "   (FX-5 assigned -> excluded; unassigned RUX items regardless of state)"

say "6. Ad-hoc SLQ straight on GET /items?q=…"
qget "software = Houdini" | expect "multi_select containment (= is contains)" "FX-1"
qget "software IN (Maya, Nuke)" | expect "multi_select IN (contains any)" "FX-1,FX-6"
qget "title ~ comp" | expect "title ~ comp (case-insensitive contains)" "FX-2,FX-6"
qget "label = urgent AND NOT state = Done" | expect "NOT state = Done" "FX-1,FX-2,FX-3,FX-5"
qget "priority IN (high, blocker)" | expect "priority IN" "FX-1,FX-2"
qget "state = 'In Progress' OR state = Done" | expect "quoted state name + OR" "FX-1,FX-7"
qget "label = fx AND show = BNX OR title ~ flare" | expect "AND binds tighter than OR" "FX-7"
qget "assignee = me" | expect "assignee = me" "FX-5"
qget "key = FX-3" | expect "key = FX-3" "FX-3"
qget "number > 5 AND created >= 2020-01-01" | expect "number/date comparisons" "FX-6,FX-7"

say "7. ORDER BY changes the result order"
qget "label = urgent ORDER BY number" | expect_order "ORDER BY number" "FX-1,FX-2,FX-3,FX-5,FX-7"
qget "label = urgent ORDER BY number DESC" | expect_order "ORDER BY number DESC" "FX-7,FX-5,FX-3,FX-2,FX-1"
qget "label = urgent ORDER BY priority DESC" | expect_order "ORDER BY priority DESC (created-desc tiebreak)" "FX-1,FX-2,FX-7,FX-5,FX-3"

say "8. Parse errors -> 422 {detail, position} (+ did-you-mean)"
expect_slq_422 "unknown field w/ suggestion" "shwo = RUX" 0
expect_slq_422 "missing value" "state <" 7
expect_slq_422 "type-invalid operator" "number ~ 5" 7
BAD_VIEW_CODE=$(curl -sS -o /tmp/bad_view.$$ -w '%{http_code}' -b "$JAR" -X POST "$API/views" -H 'content-type: application/json' \
  -d "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"bad\",\"view_type\":\"list\",\"query\":\"shwo = RUX\"}")
echo "POST /views with bad query -> HTTP $BAD_VIEW_CODE $(cat /tmp/bad_view.$$)"
python3 -c "
import json
body = json.load(open('/tmp/bad_view.$$'))
assert '$BAD_VIEW_CODE' == '422' and body['position'] == 0, (body, '$BAD_VIEW_CODE')
print('OK   view save validates SLQ with position')"
rm -f /tmp/bad_view.$$

say "9. Axis validation: swimlane_by/group_by tokens"
same_axis=$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X POST "$API/views" -H 'content-type: application/json' \
  -d "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"dup\",\"view_type\":\"board\",\"group_by\":\"state\",\"swimlane_by\":\"state\"}")
non_select=$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X POST "$API/views" -H 'content-type: application/json' \
  -d "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"num\",\"view_type\":\"board\",\"swimlane_by\":\"cf.budget\"}")
ghost_cf=$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X POST "$API/views" -H 'content-type: application/json' \
  -d "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"ghost\",\"view_type\":\"board\",\"swimlane_by\":\"cf.ghost\"}")
bad_token=$(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X POST "$API/views" -H 'content-type: application/json' \
  -d "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"tok\",\"view_type\":\"board\",\"group_by\":\"flavor\"}")
echo "swimlane_by == group_by      -> HTTP $same_axis (expect 409)"
echo "swimlane_by = cf.budget      -> HTTP $non_select (expect 409: number, not select)"
echo "swimlane_by = cf.ghost       -> HTTP $ghost_cf (expect 409: unknown key)"
echo "group_by = flavor            -> HTTP $bad_token (expect 422: bad token shape)"
[ "$same_axis" = 409 ] && [ "$non_select" = 409 ] && [ "$ghost_cf" = 409 ] && [ "$bad_token" = 422 ]

say "10. Vik (plain workspace member): sees shared view, NOT the admin's personal one"
VIK_ID=$(post /users "{\"email\":\"vik-$RUN@example.com\",\"name\":\"Vik Viewer\",\"password\":\"vik-pass-123\"}" | jget "['id']")
post "/workspaces/$WS_ID/members" "{\"user_id\":\"$VIK_ID\",\"role\":\"member\"}" > /dev/null
login "$VIK_JAR" "vik-$RUN@example.com" "vik-pass-123"
curl -sS -b "$VIK_JAR" "$API/views?workspace_id=$WS_ID" | python3 -c "
import json, sys
views = json.load(sys.stdin)
names = sorted(v['name'] for v in views)
assert names == ['FX urgent'], f'expected only the shared view, got {names}'
print(f'OK   vik lists: {names} (personal views of others are invisible)')"

say "11. Non-owner cannot touch another user's personal view (404), member cannot manage shared (403)"
echo "vik PATCH admin's personal view -> HTTP $(curl -sS -o /dev/null -w '%{http_code}' -b "$VIK_JAR" -X PATCH "$API/views/$PERSONAL_ID" -H 'content-type: application/json' -d '{"name":"hijacked"}')"
echo "vik DELETE admin's personal view -> HTTP $(curl -sS -o /dev/null -w '%{http_code}' -b "$VIK_JAR" -X DELETE "$API/views/$PERSONAL_ID")"
echo "vik PATCH the shared view       -> HTTP $(curl -sS -o /dev/null -w '%{http_code}' -b "$VIK_JAR" -X PATCH "$API/views/$SHARED_ID" -H 'content-type: application/json' -d '{"name":"nope"}')"
echo "vik POST a shared view          -> HTTP $(curl -sS -o /dev/null -w '%{http_code}' -b "$VIK_JAR" -X POST "$API/views" -H 'content-type: application/json' -d "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"nope\",\"view_type\":\"list\",\"shared\":true}")"
echo "vik POST a personal view        -> HTTP $(curl -sS -o /dev/null -w '%{http_code}' -b "$VIK_JAR" -X POST "$API/views" -H 'content-type: application/json' -d "{\"workspace_id\":\"$WS_ID\",\"project_id\":\"$P_ID\",\"name\":\"Vik's own\",\"view_type\":\"list\"}")"

say "12. Update: query re-validated, swimlane cleared with explicit null"
patch "/views/$SHARED_ID" '{"query":"label = urgent AND show = RUX AND category IN (triage, in_progress) ORDER BY priority DESC","swimlane_by":null}' | python3 -c "
import json, sys
view = json.load(sys.stdin)
assert 'ORDER BY' in view['query'] and view['swimlane_by'] is None
print('OK   query updated (with ORDER BY) and swimlane cleared')"
get "/items?$(get "/views?workspace_id=$WS_ID&project_id=$P_ID" | python3 -c "
import json,sys; print(next(v['query_string'] for v in json.load(sys.stdin) if v['id']=='$SHARED_ID'))")" \
  | expect_order "updated view orders by priority" "FX-1,FX-2,FX-5"

say "13. Full CRUD emits events (rename + delete a throwaway view)"
patch "/views/$SHARED_ID" '{"name":"FX urgent (triage+wip)"}' | jget "['name']"
TMP_ID=$(post /views "{\"workspace_id\":\"$WS_ID\",\"name\":\"scratch\",\"view_type\":\"list\"}" | jget "['id']")
curl -sS -b "$JAR" -X DELETE "$API/views/$TMP_ID" -o /dev/null -w 'DELETE scratch -> HTTP %{http_code}\n'
COOKIE="radd_session=$(awk '$6=="radd_session" {print $7}' "$JAR" | tail -1)"
python3 - "$API" "$WS_ID" "$COOKIE" <<'PY'
import json, sys, urllib.request
api, ws, cookie, after = sys.argv[1], sys.argv[2], sys.argv[3], 0
rows = []
while True:  # page the whole stream; keep this run's view.* events
    request = urllib.request.Request(f"{api}/events?after={after}&limit=500", headers={"Cookie": cookie})
    with urllib.request.urlopen(request) as response:
        page = json.load(response)
    if not page:
        break
    rows += [e for e in page if e["workspace_id"] == ws and e["event_type"].startswith("view.")]
    after = page[-1]["id"]
for e in rows:
    print(f"{e['id']:>4}  actor={(e['actor_id'] or '-')[:8]:<8}  {e['event_type']:<14} {e['payload']['name']!r} shared={e['payload']['shared']}")
types = [e["event_type"] for e in rows]
for expected in ("view.created", "view.updated", "view.deleted"):
    assert expected in types, f"missing {expected} on the stream"
print("OK   view.created / view.updated / view.deleted all on the stream")
PY

say "14. SLQ autocomplete (spec 12): field / value(state) / value(cf show) contexts"
suggest() { curl -sS -b "$JAR" -G "$API/items/slq/suggest" \
  --data-urlencode "workspace_id=$WS_ID" --data-urlencode "project_id=$P_ID" --data-urlencode "q=$1"; }
suggest "" | python3 -c "
import json, sys
d = json.load(sys.stdin); vals = [s['value'] for s in d['suggestions']]
assert d['context'] == 'field', d['context']
for f in ('state', 'assignee', 'show', 'NOT'):
    assert f in vals, f'field context missing {f}: {vals}'
print(f'field context OK: {len(vals)} fields incl. state/assignee/show/NOT')"
suggest "state = " | python3 -c "
import json, sys
d = json.load(sys.stdin); byval = {s['value']: s for s in d['suggestions']}
assert d['context'] == 'value' and d['field'] == 'state', (d['context'], d['field'])
assert 'In Progress' in byval, list(byval)
assert byval['In Progress']['insert'] == '\"In Progress\"', byval['In Progress']['insert']
print(f'state values OK: {sorted(byval)} — multi-word insert quoted')"
suggest "show = " | python3 -c "
import json, sys
d = json.load(sys.stdin); vals = [s['value'] for s in d['suggestions']]
assert d['context'] == 'value' and d['field'] == 'show', (d['context'], d['field'])
assert 'RUX' in vals, vals
print(f'cf show values OK: {vals}')"

say "all green"
