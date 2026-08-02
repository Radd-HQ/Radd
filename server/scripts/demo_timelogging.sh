#!/usr/bin/env bash
# Time logging + timesheets (spec 22): per-project enablement gate, worklogs with
# Jira-style durations + work categories + notes, item estimate/logged/remaining,
# worklog edit/delete, work-category CRUD, and the workspace timesheet aggregation.
# Rerunnable (fresh workspace + per-run project key each run). Signs in as the
# seeded admin — override with DEMO_EMAIL/DEMO_PASSWORD; point at another server
# with API=… Run against a THROWAWAY DB (RADD_DATABASE_URL=…) — never live.
# NOTE (spec 86): this walkthrough predates the workspace eradication — it still
# POSTs /workspaces and threads workspace_id, which the server no longer accepts.
# Run only against a pre-spec-86 build, or update these curls to the global surface.
set -euo pipefail
API=${API:-http://localhost:8000/api/v1}
RUN=$(date +%s)
KEY="TL${RUN: -5}"   # per-run, globally-unique project key (spec 21)
DEMO_EMAIL=${DEMO_EMAIL:-${RADD_SEED_EMAIL:-hussein@hjarrar.com}}
DEMO_PASSWORD=${DEMO_PASSWORD:-${RADD_SEED_PASSWORD:-change-me}}
SERVER_DIR=$(cd "$(dirname "$0")/.." && pwd)
JAR=$(mktemp)
trap 'rm -f "$JAR"' EXIT

say()   { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
post()  { curl -sS -b "$JAR" -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }
put()   { curl -sS -b "$JAR" -X PUT "$API$1" -H 'content-type: application/json' -d "$2"; }
patch() { curl -sS -b "$JAR" -X PATCH "$API$1" -H 'content-type: application/json' -d "$2"; }
get()   { curl -sS -b "$JAR" "$API$1"; }
gget()  { curl -sS -b "$JAR" -G "$API$1" "${@:2}"; }
jget()  { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
d()     { python3 -c "import datetime,sys; print(datetime.date.today()+datetime.timedelta(days=int(sys.argv[1])))" "$1"; }
login() { curl -sS -c "$JAR" -X POST "$API/auth/login" -H 'content-type: application/json' \
            -d "{\"email\":\"$1\",\"password\":\"$2\"}"; }
code_of() {
  if [ "$#" -ge 3 ]; then
    curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X "$1" "$API$2" -H 'content-type: application/json' -d "$3"
  else
    curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X "$1" "$API$2"
  fi
}
expect_eq() { # expect_eq <label> <actual> <expected>
  if [ "$2" = "$3" ]; then echo "OK   $1: $2"; else echo "FAIL $1: $2 != $3"; exit 1; fi
}

say "0. Seed + sign in"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
login "$DEMO_EMAIL" "$DEMO_PASSWORD" > /dev/null
echo "signed in as $DEMO_EMAIL"

say "1. Fresh workspace + project $KEY"
WS_ID=$(post /workspaces "{\"name\":\"Timelog Demo\",\"slug\":\"tlog-$RUN\"}" | jget "['id']")
P_ID=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"$KEY\",\"name\":\"Time Logging\"}" | jget "['id']")
ITEM=$(post /items "{\"project_id\":\"$P_ID\",\"kind\":\"issue\",\"title\":\"Render farm outage\"}")
I_ID=$(echo "$ITEM" | jget "['id']")
I_KEY=$(echo "$ITEM" | jget "['key']")
echo "workspace $WS_ID / project $KEY / item $I_KEY"

say "2. Enablement gate: logging is rejected until the project turns it on"
expect_eq "log before enable -> 409" "$(code_of POST "/items/$I_ID/worklogs" '{"time_spent":"1h"}')" "409"
put "/projects/$P_ID/timelogging" '{"enabled":true}' | jget "['enabled']" | grep -q true && echo "OK   enabled time logging on $KEY"

say "3. Work categories seeded on the workspace"
get "/work-categories?workspace_id=$WS_ID" | python3 -c "
import json,sys; cats=[c['name'] for c in json.load(sys.stdin)]
assert 'Code Review' in cats and 'Investigation' in cats, cats
print('OK   default categories:', ', '.join(cats))"
CAT_ID=$(gget "/work-categories" --data-urlencode "workspace_id=$WS_ID" | python3 -c "
import json,sys; print(next(c['id'] for c in json.load(sys.stdin) if c['name']=='Code Review'))")

say "4. Estimate + log work (Jira-style durations, a category, a note)"
put "/items/$I_ID/estimate" '{"estimate":"1d"}' > /dev/null
W1=$(post "/items/$I_ID/worklogs" "{\"time_spent\":\"2h 30m\",\"category_id\":\"$CAT_ID\",\"note\":\"triaged the queue\"}")
W1_ID=$(echo "$W1" | jget "['id']")
expect_eq "worklog1 seconds" "$(echo "$W1" | jget "['time_spent_seconds']")" "9000"
expect_eq "worklog1 formatted" "$(echo "$W1" | jget "['time_spent']")" "2h 30m"
post "/items/$I_ID/worklogs" "{\"time_spent\":\"45m\",\"worked_on\":\"$(d -1)\"}" > /dev/null

say "5. Summary: estimate 1d, logged 3h15m, remaining 4h45m"
SUM=$(get "/items/$I_ID/timelog")
expect_eq "original_estimate" "$(echo "$SUM" | jget "['original_estimate']")" "1d"
expect_eq "logged" "$(echo "$SUM" | jget "['logged']")" "3h 15m"
expect_eq "remaining" "$(echo "$SUM" | jget "['remaining']")" "4h 45m"
expect_eq "entry count" "$(echo "$SUM" | jget "[\"entries\"].__len__()")" "2"

say "6. Edit a worklog (clear category, bump to 3h) + delete the other"
patch "/worklogs/$W1_ID" '{"time_spent":"3h","category_id":null}' | python3 -c "
import json,sys; w=json.load(sys.stdin)
assert w['time_spent']=='3h' and w['category'] is None, w
print('OK   worklog1 -> 3h, category cleared')"
W2_ID=$(get "/items/$I_ID/timelog" | python3 -c "
import json,sys; e=[w for w in json.load(sys.stdin)['entries'] if w['time_spent_seconds']==2700][0]; print(e['id'])")
expect_eq "delete worklog2 -> 204" "$(code_of DELETE "/worklogs/$W2_ID")" "204"
expect_eq "logged after edits" "$(get "/items/$I_ID/timelog" | jget "['logged']")" "3h"

say "7. Add a work category"
post /work-categories "{\"workspace_id\":\"$WS_ID\",\"name\":\"Bug Fixing $RUN\"}" | jget "['name']" \
  | grep -q "Bug Fixing" && echo "OK   created a custom category"

say "8. Timesheet for the last 7 days"
TS=$(gget "/timesheet" \
  --data-urlencode "workspace_id=$WS_ID" \
  --data-urlencode "start=$(d -7)" \
  --data-urlencode "end=$(d 0)")
echo "$TS" | python3 -c "
import json,sys; ts=json.load(sys.stdin)
assert ts['total_seconds']==10800, ts['total_seconds']
assert len(ts['entries'])==1, ts['entries']
e=ts['entries'][0]
assert e['item']['key']=='$I_KEY' and e['user']['name'], e
print(f'OK   timesheet total={ts[\"total_seconds\"]}s across {len(ts[\"entries\"])} entr(y/ies) on {e[\"item\"][\"key\"]}')"
expect_eq "timesheet filtered to project" \
  "$(gget "/timesheet" --data-urlencode "workspace_id=$WS_ID" --data-urlencode "start=$(d -7)" --data-urlencode "end=$(d 0)" --data-urlencode "project_id=$P_ID" | jget "['total_seconds']")" \
  "10800"

say "All timelogging checks passed ✅"
