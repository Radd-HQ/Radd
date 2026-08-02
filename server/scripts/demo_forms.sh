#!/usr/bin/env bash
# Intake forms (spec 17): a template-scoped form captures structured input against the
# field registry and creates a work item with defaults applied. Proves: create a form
# (2 registry fields, one required via override, defaults kind/label/state); render
# GET /forms/{id}; a valid submit creates an item carrying the defaults + values; a
# submit missing the required field -> 422 naming it; a submit with an unknown field
# value -> 422 from the registry; and form.created/.updated/.deleted land on the stream.
# Rerunnable (fresh workspace each run). Signs in as the seeded admin — override with
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
JAR=$(mktemp)
trap 'rm -f "$JAR"' EXIT

say()   { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
post()  { curl -sS -b "$JAR" -X POST "$API$1" -H 'content-type: application/json' -d "$2"; }
patch() { curl -sS -b "$JAR" -X PATCH "$API$1" -H 'content-type: application/json' -d "$2"; }
get()   { curl -sS -b "$JAR" "$API$1"; }
pp()    { python3 -m json.tool; }
jget()  { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }
login() { curl -sS -c "$1" -X POST "$API/auth/login" -H 'content-type: application/json' \
    -d "{\"email\":\"$2\",\"password\":\"$3\"}"; }
# submit_expect_422 <label> <json-body> <expected-detail-substring> <expected-key-in-errors>
submit_expect_422() {
  local code
  code=$(curl -sS -o /tmp/forms_err.$$ -w '%{http_code}' -b "$JAR" -X POST "$API/forms/$FORM_ID/submit" \
    -H 'content-type: application/json' -d "$2")
  python3 -c "
import json, sys
code, label, detail_sub, key = '$code', sys.argv[1], sys.argv[2], sys.argv[3]
body = json.load(open('/tmp/forms_err.$$'))
assert code == '422', f'{label}: expected 422, got {code}: {body}'
assert detail_sub in body['detail'], f'{label}: detail {body[\"detail\"]!r} lacks {detail_sub!r}'
joined = '; '.join(body.get('errors', []))
assert key in joined, f'{label}: errors {body.get(\"errors\")!r} do not name {key!r}'
print(f'OK   {label}: 422 detail={body[\"detail\"]!r} errors={body.get(\"errors\")}')" "$1" "$3" "$4"
  rm -f /tmp/forms_err.$$
}

say "0. Seed + sign in"
(cd "$SERVER_DIR" && uv run python -m radd.seed --email "$DEMO_EMAIL" --password "$DEMO_PASSWORD" > /dev/null)
login "$JAR" "$DEMO_EMAIL" "$DEMO_PASSWORD"
echo "signed in as $DEMO_EMAIL"

say "1. Fresh workspace + project PS; select fields severity[Low/Med/High], area[Comp/FX/Light]"
WS_ID=$(post /workspaces "{\"name\":\"Forms Demo\",\"slug\":\"forms-$RUN\"}" | jget "['id']")
P_ID=$(post /projects "{\"workspace_id\":\"$WS_ID\",\"key\":\"PS\",\"name\":\"Proposal Support\"}" | jget "['id']")
post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"severity\",\"name\":\"Severity\",\"type\":\"select\",\"options\":[\"Low\",\"Medium\",\"High\"]}" > /dev/null
post /fields "{\"workspace_id\":\"$WS_ID\",\"key\":\"area\",\"name\":\"Area\",\"type\":\"select\",\"options\":[\"Comp\",\"FX\",\"Lighting\"]}" > /dev/null
echo "project PS ($P_ID) ready with 2 select fields (neither registry-required)"

say "2. Create an intake form: exposes severity + area, area REQUIRED via override; defaults kind=issue, label=intake, state=In Progress"
FORM=$(post /forms "{
  \"project_id\":\"$P_ID\",
  \"name\":\"Artist support request\",
  \"description\":\"Tell us what broke.\",
  \"title_prompt\":\"What do you need?\",
  \"fields\":[
    {\"field_key\":\"severity\",\"label_override\":\"How bad?\",\"help\":\"Pick a severity\",\"required\":false},
    {\"field_key\":\"area\",\"required\":true}
  ],
  \"defaults\":{\"kind\":\"issue\",\"priority\":\"high\",\"labels\":[\"intake\"],\"state_name\":\"In Progress\"}
}")
echo "$FORM" | pp
FORM_ID=$(echo "$FORM" | jget "['id']")
echo "$FORM" | python3 -c "
import json, sys
f = json.load(sys.stdin)
assert f['title_prompt'] == 'What do you need?'
keys = [x['field_key'] for x in f['fields']]
assert keys == ['severity', 'area'], keys
req = {x['field_key']: x['required'] for x in f['fields']}
assert req == {'severity': False, 'area': True}, req
assert f['defaults']['kind'] == 'issue' and f['defaults']['labels'] == ['intake']
assert f['defaults']['state_name'] == 'In Progress' and f['defaults']['priority'] == 'high'
print('OK   form stored: ordered fields, required override on area, defaults intact')"

say "3. Reject a form field_key that is not in the project's registry scope -> 409"
BAD=$(curl -sS -o /tmp/badf.$$ -w '%{http_code}' -b "$JAR" -X POST "$API/forms" -H 'content-type: application/json' \
  -d "{\"project_id\":\"$P_ID\",\"name\":\"bad\",\"fields\":[{\"field_key\":\"ghost\",\"required\":true}]}")
echo "POST /forms with unknown field_key -> HTTP $BAD $(cat /tmp/badf.$$)"; rm -f /tmp/badf.$$
[ "$BAD" = 409 ] && echo "OK   unknown field_key rejected on write (409)"

say "4. Render the form (GET /forms/{id}) as a submitter would"
get "/forms/$FORM_ID" | python3 -c "
import json, sys
f = json.load(sys.stdin)
print('render:', f['name'], '/ prompt:', repr(f['title_prompt']))
for x in f['fields']:
    print('   field', x['field_key'], 'label=', x.get('label_override'), 'required=', x['required'])
print('   defaults:', f['defaults'])"

say "5. Valid submit -> creates a work item with defaults + values"
ITEM=$(post "/forms/$FORM_ID/submit" "{\"title\":\"Fire sim won't cache\",\"values\":{\"severity\":\"High\",\"area\":\"FX\"}}")
echo "$ITEM" | pp
echo "$ITEM" | python3 -c "
import json, sys
i = json.load(sys.stdin)
assert i['title'] == \"Fire sim won't cache\", i['title']
assert i['kind'] == 'issue', i['kind']
assert i['priority'] == 'high', i['priority']
assert i['state']['name'] == 'In Progress', i['state']
assert 'intake' in i['labels'], i['labels']
assert i['custom_fields'] == {'severity': 'High', 'area': 'FX'}, i['custom_fields']
print(f\"OK   created {i['key']}: defaults applied (issue/high/In Progress/intake) + custom_fields {i['custom_fields']}\")"

say "6. Submit MISSING the required field (area) -> 422 naming it (form override)"
submit_expect_422 "missing required area" \
  "{\"title\":\"No area given\",\"values\":{\"severity\":\"High\"}}" \
  "form submission" "area: required"

say "7a. Submit an UNKNOWN field value -> 422 from the registry"
submit_expect_422 "unknown field key" \
  "{\"title\":\"Bogus field\",\"values\":{\"area\":\"FX\",\"mystery\":\"x\"}}" \
  "custom field validation" "mystery: unknown field"

say "7b. Submit an out-of-range select value -> 422 from the registry"
submit_expect_422 "invalid select value" \
  "{\"title\":\"Bad severity\",\"values\":{\"area\":\"FX\",\"severity\":\"Critical\"}}" \
  "custom field validation" "severity"

say "8. Update the form (PATCH) then delete a throwaway -> form.created/.updated/.deleted on the stream"
patch "/forms/$FORM_ID" '{"enabled":false,"description":"Paused for the holidays."}' | jget "['enabled']" | sed 's/^/enabled now: /'
TMP_FORM=$(post /forms "{\"project_id\":\"$P_ID\",\"name\":\"scratch form\"}" | jget "['id']")
curl -sS -b "$JAR" -X DELETE "$API/forms/$TMP_FORM" -o /dev/null -w 'DELETE scratch form -> HTTP %{http_code}\n'
echo "submit against the now-disabled form -> HTTP $(curl -sS -o /dev/null -w '%{http_code}' -b "$JAR" -X POST "$API/forms/$FORM_ID/submit" -H 'content-type: application/json' -d '{"title":"nope","values":{"area":"FX"}}') (expect 409: disabled)"
COOKIE="radd_session=$(awk '$6=="radd_session" {print $7}' "$JAR" | tail -1)"
python3 - "$API" "$WS_ID" "$COOKIE" <<'PY'
import json, sys, urllib.request
api, ws, cookie, after = sys.argv[1], sys.argv[2], sys.argv[3], 0
rows = []
while True:
    req = urllib.request.Request(f"{api}/events?after={after}&limit=500", headers={"Cookie": cookie})
    with urllib.request.urlopen(req) as resp:
        page = json.load(resp)
    if not page:
        break
    rows += [e for e in page if e["workspace_id"] == ws and e["event_type"].startswith("form.")]
    after = page[-1]["id"]
for e in rows:
    print(f"{e['id']:>4}  {e['event_type']:<13} {e['payload']['name']!r} enabled={e['payload']['enabled']}")
types = {e["event_type"] for e in rows}
for expected in ("form.created", "form.updated", "form.deleted"):
    assert expected in types, f"missing {expected} on the stream: {types}"
print("OK   form.created / form.updated / form.deleted all on the stream")
PY

say "all green"
