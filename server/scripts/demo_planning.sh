#!/usr/bin/env bash
# Cycles + releases + item planning (spec 14): derived cycle status, project releases
# with released_at stamping, item start/target dates, cycle/release assignment,
# dependency links (blocks/relates/duplicates), and the new SLQ fields incl. a suggest
# value call. Rerunnable (fresh workspace each run). Signs in as the seeded admin —
# override with DEMO_EMAIL/DEMO_PASSWORD; point at another server with API=…
# NOTE (spec 86): this walkthrough predates the workspace eradication — it still
# POSTs /workspaces and threads workspace_id, which the server no longer accepts.
# Run only against a pre-spec-86 build, or update these curls to the global surface.
set -euo pipefail
API=${API:-http://localhost:8000/api/v1}
RUN=$(date +%s)
DEMO_EMAIL=${DEMO_EMAIL:-${RADD_SEED_EMAIL:-hussein@hjarrar.com}}
DEMO_PASSWORD=${DEMO_PASSWORD:-${RADD_SEED_PASSWORD:-change-me}}
SERVER_DIR=$(cd "$(dirname "$0")/.." && pwd)
JAR=$(mktemp)
trap 'rm -f "$JAR"' EXIT

say()   { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
post()  { curl -sS -b "$JAR" -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }
patch() { curl -sS -b "$JAR" -X PATCH "$API$1" -H 'content-type: application/json' -d "$2"; }
del()   { curl -sS -b "$JAR" -o /dev/null -w '%{http_code}' -X DELETE "$API$1"; }
get()   { curl -sS -b "$JAR" "$API$1"; }
qget()  { curl -sS -b "$JAR" -G "$API/items" --data-urlencode "project_id=$P_ID" --data-urlencode "q=$1"; }
jget()  { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
d()     { python3 -c "import datetime,sys; print(datetime.date.today()+datetime.timedelta(days=int(sys.argv[1])))" "$1"; }
login() { curl -sS -c "$JAR" -X POST "$API/auth/login" -H 'content-type: application/json' \
            -d "{\"email\":\"$1\",\"password\":\"$2\"}"; }
code_of() { # code_of METHOD PATH [body]  -> prints HTTP status only
  if [ "$#" -ge 3 ]; then
    curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X "$1" "$API$2" -H 'content-type: application/json' -d "$3"
  else
    curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X "$1" "$API$2"
  fi
}
expect() { # expect <label> <expected-comma-separated-item-keys>  (json list on stdin; any order)
  python3 -c "
import json, sys
expected = sorted(x for x in sys.argv[2].split(',') if x)
got = sorted(i['key'] for i in json.load(sys.stdin))
ok = got == expected
print(('OK   ' if ok else 'FAIL ') + f'{sys.argv[1]}: {got}' + ('' if ok else f' != expected {expected}'))
sys.exit(0 if ok else 1)" "$1" "$2"
}

say "0. Seed + sign in"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
login "$DEMO_EMAIL" "$DEMO_PASSWORD"
echo "signed in as $DEMO_EMAIL"

say "1. Fresh workspace 'Planning Demo' + project PIPE"
WS_ID=$(post /workspaces "{\"name\":\"Planning Demo\",\"slug\":\"plan-$RUN\"}" | jget "['id']")
P_ID=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"PIPE\",\"name\":\"Pipeline\"}" | jget "['id']")
echo "workspace $WS_ID / project PIPE $P_ID"

say "2. Cycles: derived status upcoming / active / completed"
CYCLE_NAME="Sprint Alpha $RUN"
ACTIVE=$(post /cycles "{\"workspace_id\":\"$WS_ID\",\"name\":\"$CYCLE_NAME\",\"start_date\":\"$(d -3)\",\"end_date\":\"$(d 10)\",\"goal\":\"land the fluid solver\"}")
echo "$ACTIVE" | python3 -c "
import json,sys; c=json.load(sys.stdin)
assert c['status']=='active', c['status']
print(f'OK   active cycle {c[\"name\"]!r} start={c[\"start_date\"]} end={c[\"end_date\"]} -> status={c[\"status\"]}')"
CYCLE_ID=$(echo "$ACTIVE" | jget "['id']")
UPCOMING=$(post /cycles "{\"workspace_id\":\"$WS_ID\",\"name\":\"Sprint Beta $RUN\",\"start_date\":\"$(d 20)\",\"end_date\":\"$(d 34)\"}")
echo "$UPCOMING" | python3 -c "import json,sys; c=json.load(sys.stdin); assert c['status']=='upcoming', c; print(f'OK   upcoming cycle -> {c[\"status\"]}')"
DONE=$(post /cycles "{\"workspace_id\":\"$WS_ID\",\"name\":\"Sprint Zero $RUN\",\"start_date\":\"$(d -30)\",\"end_date\":\"$(d -10)\"}")
echo "$DONE" | python3 -c "import json,sys; c=json.load(sys.stdin); assert c['status']=='completed', c; print(f'OK   completed cycle -> {c[\"status\"]}')"

say "3. GET /cycles?status=active narrows to the running sprint; end<start -> 409"
get "/cycles?workspace_id=$WS_ID&status=active" | python3 -c "
import json,sys; rows=json.load(sys.stdin)
names=[c['name'] for c in rows]
assert names==['$CYCLE_NAME'], names
print(f'OK   status=active filter -> {names}')"
patch "/cycles/$CYCLE_ID" '{"goal":"land the fluid solver + cache migration"}' | python3 -c "
import json,sys; c=json.load(sys.stdin)
assert c['goal'].endswith('cache migration') and c['status']=='active', c
print('OK   cycle goal updated (status still active)')"
echo "end_date < start_date       -> HTTP $(code_of POST /cycles "{\"workspace_id\":\"$WS_ID\",\"name\":\"bad\",\"start_date\":\"$(d 5)\",\"end_date\":\"$(d 1)\"}") (expect 409)"

say "4. Release BNX.2.3 (planned) -> released stamps released_at"
REL=$(post /releases "{\"project_id\":\"$P_ID\",\"name\":\"Beans 2.3\",\"version\":\"BNX.2.3\",\"description\":\"beans show delivery\"}")
echo "$REL" | python3 -c "import json,sys; r=json.load(sys.stdin); assert r['status']=='planned' and r['released_at'] is None, r; print(f'OK   release {r[\"version\"]} planned, released_at=None')"
REL_ID=$(echo "$REL" | jget "['id']")
patch "/releases/$REL_ID" '{"status":"released"}' | python3 -c "
import json,sys; r=json.load(sys.stdin)
assert r['status']=='released' and r['released_at'] is not None, r
print(f'OK   status->released stamps released_at={r[\"released_at\"]}')"
echo "duplicate version (project)  -> HTTP $(code_of POST /releases "{\"project_id\":\"$P_ID\",\"name\":\"dup\",\"version\":\"BNX.2.3\"}") (expect 409)"

say "5. Two items; dates on A; assign A to the cycle + release"
A=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"Fluid solver crashes on cache\",\"priority\":\"blocker\"}")
A_ID=$(echo "$A" | jget "['id']"); A_KEY=$(echo "$A" | jget "['key']")
B=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"Cache format migration\"}")
B_ID=$(echo "$B" | jget "['id']"); B_NUM=$(echo "$B" | jget "['number']"); B_KEY=$(echo "$B" | jget "['key']")
echo "created $A_KEY and $B_KEY"
patch "/items/$A_ID" "{\"start_date\":\"$(d 0)\",\"target_date\":\"$(d 7)\",\"cycle_id\":\"$CYCLE_ID\",\"release_id\":\"$REL_ID\"}" | python3 -c "
import json,sys; i=json.load(sys.stdin)
assert i['start_date']=='$(d 0)' and i['target_date']=='$(d 7)', i
assert i['cycle'] and i['cycle']['name']=='$CYCLE_NAME' and i['cycle']['status']=='active', i['cycle']
assert i['release'] and i['release']['version']=='BNX.2.3' and i['release']['status']=='released', i['release']
print(f'OK   {i[\"key\"]} dates={i[\"start_date\"]}..{i[\"target_date\"]} cycle={i[\"cycle\"][\"name\"]!r}({i[\"cycle\"][\"status\"]}) release={i[\"release\"][\"version\"]}')"
echo "target_date < start_date     -> HTTP $(code_of PATCH "/items/$B_ID" "{\"start_date\":\"$(d 7)\",\"target_date\":\"$(d 1)\"}") (expect 409)"

say "6. Link $A_KEY blocks $B_KEY (by target_number); embedded links on both ends"
LINKED=$(post "/items/$A_ID/links" "{\"target_number\":$B_NUM,\"link_type\":\"blocks\"}")
echo "$LINKED" | python3 -c "
import json,sys; i=json.load(sys.stdin)
out=i['links']['outgoing']
assert len(out)==1 and out[0]['link_type']=='blocks' and out[0]['item']['key']=='$B_KEY', out
print(f'OK   {i[\"key\"]} outgoing: blocks -> {out[0][\"item\"][\"key\"]}')"
get "/items/$B_ID" | python3 -c "
import json,sys; i=json.load(sys.stdin)
inc=i['links']['incoming']
assert len(inc)==1 and inc[0]['link_type']=='blocks' and inc[0]['item']['key']=='$A_KEY', inc
print(f'OK   {i[\"key\"]} incoming: blocked by {inc[0][\"item\"][\"key\"]}')"
echo "self-link                    -> HTTP $(code_of POST "/items/$A_ID/links" "{\"target_id\":\"$A_ID\",\"link_type\":\"relates\"}") (expect 409)"
echo "duplicate blocks link        -> HTTP $(code_of POST "/items/$A_ID/links" "{\"target_number\":$B_NUM,\"link_type\":\"blocks\"}") (expect 409)"

say "7. SLQ over the new fields (scoped to PIPE)"
qget "cycle = \"$CYCLE_NAME\" AND target IS NOT EMPTY" | expect "cycle = <name> AND target IS NOT EMPTY" "$A_KEY"
qget "blocks IS NOT EMPTY"        | expect "blocks IS NOT EMPTY" "$A_KEY"
qget "blocked IS NOT EMPTY"       | expect "blocked IS NOT EMPTY" "$B_KEY"
qget "release = \"BNX.2.3\""      | expect "release = BNX.2.3" "$A_KEY"
qget "cycle IS EMPTY"             | expect "cycle IS EMPTY (unplanned)" "$B_KEY"
qget "blocks = $B_KEY"            | expect "blocks = <key> (links to that item)" "$A_KEY"
qget "start >= $(d 0) AND target < $(d 30)" | expect "start/target date range" "$A_KEY"

say "8. SLQ suggest: value context for 'cycle' lists the cycle name; 'release' lists the version"
curl -sS -b "$JAR" -G "$API/items/slq/suggest" \
  --data-urlencode "workspace_id=$WS_ID" --data-urlencode "project_id=$P_ID" --data-urlencode "q=cycle = " | python3 -c "
import json,sys; d=json.load(sys.stdin); vals={s['value']:s for s in d['suggestions']}
assert d['context']=='value' and d['field']=='cycle', (d['context'], d['field'])
assert 'none' in vals and '$CYCLE_NAME' in vals, list(vals)
assert vals['$CYCLE_NAME']['insert']=='\"$CYCLE_NAME\"', vals['$CYCLE_NAME']['insert']  # spacey name -> quoted
print(f'OK   cycle value context: {sorted(vals)} — multi-word insert quoted')"
curl -sS -b "$JAR" -G "$API/items/slq/suggest" \
  --data-urlencode "workspace_id=$WS_ID" --data-urlencode "project_id=$P_ID" --data-urlencode "q=release = " | python3 -c "
import json,sys; d=json.load(sys.stdin); vals=[s['value'] for s in d['suggestions']]
assert d['field']=='release' and 'BNX.2.3' in vals, vals
print(f'OK   release value context: {vals}')"

say "9. Unlink; deleting the cycle nulls the item's cycle_id (ON DELETE SET NULL)"
LINK_ID=$(get "/items/$A_ID" | jget "['links']['outgoing'][0]['id']")
echo "DELETE $A_KEY link           -> HTTP $(del "/items/$A_ID/links/$LINK_ID") (expect 204)"
get "/items/$A_ID" | python3 -c "import json,sys; i=json.load(sys.stdin); assert i['links']['outgoing']==[], i['links']; print('OK   link removed')"
echo "DELETE cycle                 -> HTTP $(del "/cycles/$CYCLE_ID") (expect 204)"
get "/items/$A_ID" | python3 -c "import json,sys; i=json.load(sys.stdin); assert i['cycle'] is None, i['cycle']; print('OK   item cycle nulled after cycle delete')"

say "10. cycle.* / release.* / item.updated events on the stream"
COOKIE="radd_session=$(awk '$6=="radd_session" {print $7}' "$JAR" | tail -1)"
python3 - "$API" "$WS_ID" "$COOKIE" <<'PY'
import json, sys, urllib.request
api, ws, cookie, after = sys.argv[1], sys.argv[2], sys.argv[3], 0
seen = set()
while True:
    req = urllib.request.Request(f"{api}/events?after={after}&limit=500", headers={"Cookie": cookie})
    page = json.load(urllib.request.urlopen(req))
    if not page:
        break
    for e in page:
        if e["workspace_id"] == ws:
            seen.add(e["event_type"])
    after = page[-1]["id"]
for expected in ("cycle.created", "cycle.updated", "cycle.deleted", "release.created", "release.updated"):
    assert expected in seen, f"missing {expected}; saw {sorted(seen)}"
print("OK   cycle.created/.updated/.deleted + release.created/.updated on the stream")
PY

say "all green"
