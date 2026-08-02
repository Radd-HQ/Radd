#!/usr/bin/env bash
# Reporting / dashboards (spec 16): the five read-only analytics endpoints, all computed
# on the fly from the event log + cycles (no tables). Reconstructs each item's state
# history from item.created/item.updated payloads. Rerunnable (fresh workspace each run).
# Signs in as the seeded admin — override with DEMO_EMAIL/DEMO_PASSWORD; point at another
# server with API=… (verification runs on 8003, never the supervisor's 8000).
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
get()   { curl -sS -b "$JAR" "$API$1"; }
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

say "0. Seed + sign in"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
login "$DEMO_EMAIL" "$DEMO_PASSWORD" > /dev/null
echo "signed in as $DEMO_EMAIL"

say "1. Fresh workspace 'Reporting Demo' + project RPT"
WS_ID=$(post /workspaces "{\"name\":\"Reporting Demo\",\"slug\":\"rpt-$RUN\"}" | jget "['id']")
P_ID=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"RPT\",\"name\":\"Reporting\"}" | jget "['id']")
echo "workspace $WS_ID / project RPT $P_ID"
# Resolve the seeded done- and in-progress-category state ids.
STATES=$(get "/states?project_id=$P_ID")
DONE_SID=$(echo "$STATES" | python3 -c "import json,sys; print(next(s['id'] for s in json.load(sys.stdin) if s['category']=='done'))")
INPROG_SID=$(echo "$STATES" | python3 -c "import json,sys; print(next(s['id'] for s in json.load(sys.stdin) if s['category']=='in_progress'))")

say "2. A completed cycle (velocity) + an active cycle (burnup)"
PAST=$(post /cycles "{\"workspace_id\":\"$WS_ID\",\"name\":\"Sprint Past $RUN\",\"start_date\":\"$(d -20)\",\"end_date\":\"$(d -6)\"}")
PAST_ID=$(echo "$PAST" | jget "['id']"); PAST_NAME=$(echo "$PAST" | jget "['name']")
echo "$PAST" | python3 -c "import json,sys; c=json.load(sys.stdin); assert c['status']=='completed', c; print(f'OK   completed cycle {c[\"name\"]!r}')"
NOW=$(post /cycles "{\"workspace_id\":\"$WS_ID\",\"name\":\"Sprint Now $RUN\",\"start_date\":\"$(d -3)\",\"end_date\":\"$(d 10)\"}")
NOW_ID=$(echo "$NOW" | jget "['id']"); NOW_NAME=$(echo "$NOW" | jget "['name']")
echo "$NOW" | python3 -c "import json,sys; c=json.load(sys.stdin); assert c['status']=='active', c; print(f'OK   active cycle {c[\"name\"]!r} window {c[\"start_date\"]}..{c[\"end_date\"]}')"

say "3. Five items; drive them through states (+cycle assignment) to lay down history"
new_item() { post /items "{\"project_id\":\"$P_ID\",\"title\":\"$1\"}" | jget "['id']"; }
I1=$(new_item "Fluid cache corruption"); I2=$(new_item "Denoise banding")
I3=$(new_item "Roto matte edges");     I4=$(new_item "Layout camera jitter")
I5=$(new_item "Comp holdout leak")
# I1,I2: enter Done assigned to the completed cycle (velocity source)
patch "/items/$I1" "{\"cycle_id\":\"$PAST_ID\",\"state_id\":\"$DONE_SID\"}" > /dev/null
patch "/items/$I2" "{\"cycle_id\":\"$PAST_ID\",\"state_id\":\"$DONE_SID\"}" > /dev/null
# I3: enter Done assigned to the active cycle
patch "/items/$I3" "{\"cycle_id\":\"$NOW_ID\",\"state_id\":\"$DONE_SID\"}" > /dev/null
# I4: triage -> In Progress -> Done, assigned to the active cycle (a completed in_progress stay)
patch "/items/$I4" "{\"cycle_id\":\"$NOW_ID\",\"state_id\":\"$INPROG_SID\"}" > /dev/null
patch "/items/$I4" "{\"state_id\":\"$DONE_SID\"}" > /dev/null
# I5: triage -> In Progress, assigned to the active cycle, stays open (never done)
patch "/items/$I5" "{\"cycle_id\":\"$NOW_ID\",\"state_id\":\"$INPROG_SID\"}" > /dev/null
echo "OK   4 items reached Done (I1,I2,I3,I4); I5 sits In Progress"

say "4. GET /reports/throughput — items that ENTERED a done state, bucketed by day"
get "/reports/throughput?project_id=$P_ID&interval=day" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
assert isinstance(rows,list) and rows, rows
assert all(set(r)=={'bucket','count'} for r in rows), rows
total=sum(r['count'] for r in rows)
assert total==4, f'expected 4 done-entries, got {total}: {rows}'
# The 4 completions land in one bucket; its calendar day is the event's UTC date,
# which can differ from local 'today' near midnight — assert the shape, not the day.
assert max((r['count'] for r in rows), default=0)==4, rows
print(f'OK   throughput total={total} (== items moved to done); single bucket count=4')"

say "5. GET /reports/cumulative-flow — category distribution at each bucket end"
get "/reports/cumulative-flow?project_id=$P_ID&interval=day" | python3 -c "
import json,sys,datetime
rows=json.load(sys.stdin)
assert isinstance(rows,list) and rows, rows
last=rows[-1]
assert set(last)=={'bucket','counts'}, last
cats=last['counts']
assert cats['done']==4, cats
assert cats['in_progress']==1, cats
assert cats['triage']==0 and cats['backlog']==0, cats
print(f'OK   CFD final bucket {last[\"bucket\"]}: done={cats[\"done\"]} in_progress={cats[\"in_progress\"]}')"

say "6. GET /reports/time-in-state — avg/median hours per category (completed stays)"
get "/reports/time-in-state?project_id=$P_ID" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
assert isinstance(rows,list) and rows, rows
by_cat={r['category']:r for r in rows}
assert set(rows[0])=={'category','avg_hours','median_hours','sample'}, rows[0]
assert by_cat['triage']['sample']==5, by_cat['triage']          # all 5 items left triage
assert by_cat['in_progress']['sample']==1, by_cat.get('in_progress')  # only I4's stay is closed
assert 'done' not in by_cat, 'done stays are still open -> not counted'
assert all(r['avg_hours']>=0 and r['median_hours']>=0 for r in rows), rows
print(f'OK   time-in-state: triage sample={by_cat[\"triage\"][\"sample\"]}, in_progress sample={by_cat[\"in_progress\"][\"sample\"]}')"
# kind filter is accepted and scopes the sample
get "/reports/time-in-state?project_id=$P_ID&kind=epic" | python3 -c "
import json,sys; rows=json.load(sys.stdin); assert rows==[], rows; print('OK   kind=epic filter -> no issue stays (empty)')"

say "7. GET /reports/velocity — completed items per recent completed cycle"
get "/reports/velocity?workspace_id=$WS_ID&last=5" | python3 -c "
import json,sys
rows=json.load(sys.stdin)
assert isinstance(rows,list) and rows, rows
assert all(set(r)=={'cycle','completed'} and set(r['cycle'])=={'id','name'} for r in rows), rows
past=[r for r in rows if r['cycle']['name']=='$PAST_NAME']
assert past and past[0]['completed']==2, rows
assert all(r['cycle']['name']!='$NOW_NAME' for r in rows), 'active cycle must not appear'
print(f'OK   velocity lists {[r[\"cycle\"][\"name\"] for r in rows]}; {past[0][\"cycle\"][\"name\"]!r} completed={past[0][\"completed\"]}')"

say "8. GET /reports/burnup — daily scope vs completed over the cycle window"
get "/reports/burnup?cycle_id=$NOW_ID" | python3 -c "
import json,sys,datetime
b=json.load(sys.stdin)
assert set(b)=={'cycle','series'}, list(b)
assert set(b['cycle'])=={'id','name','start_date','end_date'}, b['cycle']
s=b['series']
start=datetime.date.fromisoformat(b['cycle']['start_date']); end=datetime.date.fromisoformat(b['cycle']['end_date'])
assert len(s)==(end-start).days+1, f'series must cover every day of the window: {len(s)} vs {(end-start).days+1}'
assert s[0]['date']==b['cycle']['start_date'] and s[-1]['date']==b['cycle']['end_date'], (s[0],s[-1])
assert all(set(p)=={'date','scope','completed'} for p in s), s
assert s[-1]['scope']==3, s[-1]      # I3,I4,I5 assigned to the active cycle
assert s[-1]['completed']==2, s[-1]  # I3,I4 reached done in it
assert s[0]['scope']==0, s[0]        # nothing assigned yet at window start
assert all(p['completed']<=p['scope'] for p in s), s
print(f'OK   burnup covers {len(s)} days; final scope={s[-1][\"scope\"]} completed={s[-1][\"completed\"]}')"

say "9. Guards: reversed window -> 422; unknown project -> 404; anon -> 401"
echo "start > end                  -> HTTP $(code_of GET "/reports/throughput?project_id=$P_ID&start=$(d 0)&end=$(d -5)") (expect 422)"
echo "unknown project              -> HTTP $(code_of GET "/reports/throughput?project_id=11111111-1111-1111-1111-111111111111") (expect 404)"
echo "anonymous (no cookie)        -> HTTP $(curl -sS -o /dev/null -w '%{http_code}' "$API/reports/velocity?workspace_id=$WS_ID") (expect 401)"

say "all green"
