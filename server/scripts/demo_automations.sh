#!/usr/bin/env bash
# Automations rules engine (spec 15): a rule matches new items via SLQ and applies
# actions asynchronously as the system actor; a non-matching item is untouched; a rule
# keyed on its own effect does NOT spin (loop guard); and POST /test previews a rule
# without writing. Rerunnable (fresh workspace each run). Signs in as the seeded admin —
# override with DEMO_EMAIL/DEMO_PASSWORD; point at another server with API=…
#
# The engine runs in-process, so verify against a server that has the automations module
# and its migration applied. To keep the shared live DB safe, run it against an ISOLATED
# database + server (see the header of the block at the bottom of this file's PR notes):
#   createdb radd_auto; RADD_DATABASE_URL=…/radd_auto alembic upgrade heads; seed;
#   uvicorn … --port 8002;  API=http://localhost:8002/api/v1 ./scripts/demo_automations.sh
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

# Well-known automation system actor (radd.modules.automations.types.SYSTEM_ACTOR_ID) —
# every engine-applied mutation is tagged with it; the engine skips its own events.
SYSTEM_ACTOR_ID="00000000-0000-0000-0000-000000a70a70"

say()   { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
post()  { curl -sS -b "$JAR" -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }
patch() { curl -sS -b "$JAR" -X PATCH "$API$1" -H 'content-type: application/json' -d "$2"; }
get()   { curl -sS -b "$JAR" "$API$1"; }
jget()  { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
login() { curl -sS -c "$JAR" -X POST "$API/auth/login" -H 'content-type: application/json' \
            -d "{\"email\":\"$1\",\"password\":\"$2\"}"; }

wait_item() { # wait_item ITEM_ID PY_PRED [tries]  — polls GET /items/{id} until pred(i) true
  local tries=${3:-30}
  for _ in $(seq 1 "$tries"); do
    if get "/items/$1" | python3 -c "import json,sys; i=json.load(sys.stdin); sys.exit(0 if ($2) else 1)" 2>/dev/null; then
      return 0
    fi
    sleep 0.5
  done
  echo "TIMEOUT waiting for [$2] on $1:"; get "/items/$1" | python3 -m json.tool; return 1
}

say "0. Seed + sign in"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
login "$DEMO_EMAIL" "$DEMO_PASSWORD"
echo "signed in as $DEMO_EMAIL"

say "1. Fresh workspace 'Automations Demo' + project TD"
WS_ID=$(post /workspaces "{\"name\":\"Automations Demo\",\"slug\":\"auto-$RUN\"}" | jget "['id']")
P_ID=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"TD\",\"name\":\"Tracker\"}" | jget "['id']")
echo "workspace $WS_ID / project TD $P_ID"

say "2. Rule R1 — on item_created WHERE priority = blocker: add label 'urgent' + set state 'Code Review' + internal comment"
R1=$(post /automations "{\"workspace_id\":\"$WS_ID\",\"name\":\"Blocker triage\",\"trigger\":\"item_created\",\"condition_slq\":\"priority = blocker\",\"actions\":[{\"type\":\"add_label\",\"params\":{\"label\":\"urgent\"}},{\"type\":\"set_state\",\"params\":{\"state\":\"Code Review\"}},{\"type\":\"add_comment\",\"params\":{\"body\":\"auto-triaged: blocker escalated to Code Review\",\"visibility\":\"internal\"}}]}")
echo "$R1" | python3 -m json.tool
R1_ID=$(echo "$R1" | jget "['id']")

say "3. Create a MATCHING item (priority blocker) and a NON-matching one (priority normal)"
MATCH=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"prod is down\",\"priority\":\"blocker\"}")
MATCH_ID=$(echo "$MATCH" | jget "['id']"); MATCH_KEY=$(echo "$MATCH" | jget "['key']")
OTHER=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"tweak the footer\",\"priority\":\"normal\"}")
OTHER_ID=$(echo "$OTHER" | jget "['id']"); OTHER_KEY=$(echo "$OTHER" | jget "['key']")
echo "created $MATCH_KEY (blocker) and $OTHER_KEY (normal); waiting for the async engine…"

say "4. The matching item got the label + review state + comment; the other is untouched"
wait_item "$MATCH_ID" "'urgent' in i['labels'] and i['state']['name']=='Code Review' and i['comment_count']>=1"
get "/items/$MATCH_ID" | python3 -c "
import json,sys; i=json.load(sys.stdin)
assert 'urgent' in i['labels'] and i['state']['name']=='Code Review' and i['comment_count']>=1, i
print(f'OK   {i[\"key\"]}: labels={i[\"labels\"]} state={i[\"state\"][\"name\"]!r} comments={i[\"comment_count\"]} (rule applied async)')"
get "/items/$MATCH_ID/comments" | python3 -c "
import json,sys; c=json.load(sys.stdin)
assert any('auto-triaged' in x['body'] and x['visibility']=='internal' for x in c), c
print(f'OK   {len(c)} comment(s) by the automation system actor: {c[0][\"author\"][\"name\"]!r} / {c[0][\"visibility\"]}')"
sleep 2  # give the engine a chance to (wrongly) touch the non-matching item, to prove it doesn't
get "/items/$OTHER_ID" | python3 -c "
import json,sys; i=json.load(sys.stdin)
assert i['labels']==[] and i['state']['name']=='Triage', i
print(f'OK   {i[\"key\"]}: labels={i[\"labels\"]} state={i[\"state\"][\"name\"]!r} (non-matching, untouched)')"

say "5. Loop guard — R2 sets priority=high on items WHERE priority=high (keyed on its own effect)"
R2_ID=$(post /automations "{\"workspace_id\":\"$WS_ID\",\"name\":\"Self-referential\",\"trigger\":\"item_updated\",\"condition_slq\":\"priority = high\",\"actions\":[{\"type\":\"set_priority\",\"params\":{\"priority\":\"high\"}}]}" | jget "['id']")
LOOP=$(post /items "{\"project_id\":\"$P_ID\",\"title\":\"escalate me\",\"priority\":\"normal\"}")
LOOP_ID=$(echo "$LOOP" | jget "['id']"); LOOP_KEY=$(echo "$LOOP" | jget "['key']")
echo "created $LOOP_KEY; raising priority to high (fires R2, whose effect re-satisfies R2)…"
patch "/items/$LOOP_ID" '{"priority":"high"}' > /dev/null
wait_item "$LOOP_ID" "i['priority']=='high'"

count_auto_updates() { # count item.updated events for LOOP_ID caused by the system actor
  COOKIE="radd_session=$(awk '$6=="radd_session" {print $7}' "$JAR" | tail -1)"
  python3 - "$API" "$COOKIE" "$LOOP_ID" "$SYSTEM_ACTOR_ID" <<'PY'
import json, sys, urllib.request
api, cookie, item_id, sysid, after, n = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], 0, 0
while True:
    req = urllib.request.Request(f"{api}/events?after={after}&limit=500", headers={"Cookie": cookie})
    page = json.load(urllib.request.urlopen(req))
    if not page:
        break
    for e in page:
        if e["event_type"] == "item.updated" and e["entity_id"] == item_id and e["actor_id"] == sysid:
            n += 1
    after = page[-1]["id"]
print(n)
PY
}
# Wait for the engine to apply R2 once (its effect re-satisfies R2's own condition)…
N1=0
for _ in $(seq 1 30); do N1=$(count_auto_updates); [ "$N1" -ge 1 ] && break; sleep 0.5; done
sleep 3  # …then confirm it settled: a broken guard would keep re-applying and this would grow
N2=$(count_auto_updates)
python3 -c "
n1, n2 = int('$N1'), int('$N2')
assert n1 == 1 and n2 == 1, f'loop guard FAILED: automation-caused item.updated count {n1} -> {n2} (expected a stable 1)'
print(f'OK   $LOOP_KEY priority=high; the engine applied R2 exactly once and stopped: automation-caused item.updated = {n1}, still {n2} after +3s (no spin)')"

say "6. POST /automations/{id}/test — dry-run preview (no writes)"
post "/automations/$R1_ID/test" "{\"item_id\":\"$MATCH_ID\"}" | python3 -c "
import json,sys; r=json.load(sys.stdin)
assert r['matched'] is True and len(r['would_apply'])==3 and all(a['resolves'] for a in r['would_apply']), r
print('OK   preview vs blocker item: matched=True; would_apply=' + str([f\"{a['type']}:{a['detail']}\" for a in r['would_apply']]))"
post "/automations/$R1_ID/test" "{\"item_id\":\"$OTHER_ID\"}" | python3 -c "
import json,sys; r=json.load(sys.stdin)
assert r['matched'] is False and r['would_apply']==[], r
print('OK   preview vs normal item: matched=False; would_apply=[] (no writes)')"

say "7. Rule CRUD list + automation.* events on the stream"
get "/automations?workspace_id=$WS_ID" | python3 -c "
import json,sys; rows=json.load(sys.stdin)
names=sorted(r['name'] for r in rows)
assert names==['Blocker triage','Self-referential'], names
print(f'OK   GET /automations -> {names}')"
COOKIE="radd_session=$(awk '$6=="radd_session" {print $7}' "$JAR" | tail -1)"
python3 - "$API" "$WS_ID" "$COOKIE" <<'PY'
import json, sys, urllib.request
api, ws, cookie, after, seen = sys.argv[1], sys.argv[2], sys.argv[3], 0, set()
while True:
    req = urllib.request.Request(f"{api}/events?after={after}&limit=500", headers={"Cookie": cookie})
    page = json.load(urllib.request.urlopen(req))
    if not page:
        break
    for e in page:
        if e["workspace_id"] == ws:
            seen.add(e["event_type"])
    after = page[-1]["id"]
assert "automation.created" in seen, f"missing automation.created; saw {sorted(seen)}"
print("OK   automation.created on the stream")
PY

say "all green"
