"""The scripts plugin behind an air gap (RADD-1277): does the managed
interpreter build, install and run with NO route out of the container?

Runs INSIDE the production image, against its own API, so it needs no host
tooling beyond podman. The recipe (a podman network with `--internal` has no
external route; the DB rides the same network):

    podman build -t radd-airgap -f Containerfile .
    podman network create --internal radd-airgap
    podman run -d --name ag-db --network radd-airgap -e POSTGRES_USER=radd \
        -e POSTGRES_PASSWORD=radd -e POSTGRES_DB=radd docker.io/pgvector/pgvector:pg16
    sleep 6
    podman run -d --name ag-app --network radd-airgap \
        -e RADD_DATABASE_URL=postgresql+psycopg://radd:radd@ag-db:5432/radd \
        -e RADD_APP_BASE_URL=http://127.0.0.1:8000 -e RADD_SCRIPTS_API_URL=http://127.0.0.1:8000 \
        localhost/radd-airgap
    sleep 25
    podman exec ag-app python -m radd.seed --email admin@example.com --password change-me --name Admin
    podman exec -i ag-app python3 - < server/scripts/scripts_airgap_probe.py
    podman rm -f ag-app ag-db && podman network rm radd-airgap

What it proves: the rebuild resolves the SDK and its closure from the image's
wheelhouse in seconds; an offline install of a package no wheelhouse holds
fails fast with uv's own message; a mirror URL keeps its password out of the
read model and the ledger; a script reaches the API through the venv's SDK
over `RADD_SCRIPTS_API_URL`; a wheel dropped into the operator wheelhouse on
the data volume installs by name. Exit status is the number of failed checks.
"""

import http.cookiejar
import json
import pathlib
import shutil
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    t = time.time()
    try:
        with opener.open(req, timeout=900) as r:
            raw = r.read().decode()
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        status = e.code
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = raw
    return status, data, time.time() - t


checks = []


def check(name, ok, detail=""):
    checks.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


s, me, _ = call("POST", "/auth/login", {"email": "admin@example.com", "password": "change-me"})
check("login", s in (200, 204), f"{s}")
s, it, _ = call("GET", "/scripts/interpreter")
check(
    "interpreter read: missing, sdk from a bundled wheel, image wheelhouse listed",
    s == 200
    and it["status"] == "missing"
    and it["sdk_source"].endswith(".whl")
    and "/app/wheels" in it["wheelhouses"],
    f"{it.get('status')} sdk={it.get('sdk_source')} houses={it.get('wheelhouses')}",
)

s, built, dt = call("POST", "/scripts/interpreter/rebuild", {"python_version": "3.12"})
check(
    "rebuild succeeds with no network",
    s == 200 and built["status"] == "ready",
    f"{s} status={built.get('status')} resolved={built.get('resolved')} in {dt:.1f}s",
)
if s != 200 or built["status"] != "ready":
    print(built.get("log", built)[-1500:])
check("rebuild took seconds, not a network timeout", dt < 60, f"{dt:.1f}s")
check(
    "rebuild log shows an offline resolve, never pip seeding",
    "--offline" not in built["log"]
    and "pip" not in built["log"].lower().split("radd")[0]
    and "radd-sdk" in built["log"],
    built["log"][-300:].replace("\n", " | "),
)

# Offline: an unknown package fails fast with uv's own wording.
s, it, _ = call("PUT", "/scripts/interpreter", {"index_url": "", "offline": True})
check("offline switch saved", s == 200 and it["offline"] is True, f"{s}")
s, pkg, dt = call("POST", "/scripts/packages", {"spec": "requests"})
check(
    "offline: a package in no wheelhouse fails fast and says why",
    s == 201 and pkg["status"] == "failed" and "network was disabled" in pkg["log"] and dt < 20,
    f"{s} status={pkg.get('status')} in {dt:.1f}s :: {pkg.get('log', '')[-160:].strip()}",
)

# A mirror URL with a password is masked on read and in the ledger.
s, it, _ = call(
    "PUT",
    "/scripts/interpreter",
    {"index_url": "http://radd:hunter2@mirror.local/simple", "offline": False},
)
check(
    "index url stored, password masked on read",
    s == 200 and it["index_url"] == "http://radd:***@mirror.local/simple",
    f"{it.get('index_url')}",
)
s, ledger, _ = call("GET", "/audit?entity_type=script_interpreter")
text = json.dumps(ledger)
check(
    "ledger has the update with a diff and no password",
    "script_interpreter.updated" in text and "hunter2" not in text and "mirror.local" in text,
    text[:200],
)
s, pkg, dt = call("POST", "/scripts/packages", {"spec": "requests"})
check(
    "online against an unreachable mirror: fails (no hang beyond uv's own timeout)",
    s == 201 and pkg["status"] == "failed",
    f"{s} status={pkg.get('status')} in {dt:.1f}s :: {pkg.get('log', '')[-200:].strip()}",
)
call("PUT", "/scripts/interpreter", {"index_url": "", "offline": True})

# A script that calls back into Radd through the SDK, over the in-cluster URL.
body = "def main(ctx):\n    me = ctx.client.get('/auth/me')\n    ctx.log('hello from the venv')\n    return {'email': me.get('email'), 'items': len(ctx.items)}\n"
s, run, dt = call("POST", "/scripts/run", {"body": body, "timeout": 30})
check(
    "a script runs in the venv and reaches the API through the SDK",
    s == 200 and run["ok"] and run["result"]["email"] == "admin@example.com",
    f"{s} ok={run.get('ok')} result={run.get('result')} err={run.get('error')} stderr={run.get('stderr', '').strip()[-120:]} in {dt:.1f}s",
)

# The operator wheelhouse: drop a wheel in, install by name, offline.
house = pathlib.Path(it["operator_wheelhouse"])
house.mkdir(parents=True, exist_ok=True)
src = next(pathlib.Path("/app/wheels").glob("idna-*.whl"))
shutil.copy(src, house / src.name)
s, pkg, dt = call("POST", "/scripts/packages", {"spec": "idna"})
check(
    "offline: a wheel dropped into the operator wheelhouse installs by name",
    s == 201 and pkg["status"] == "installed" and bool(pkg["resolved_version"]),
    f"{s} {pkg.get('status')} {pkg.get('resolved_version')} in {dt:.1f}s",
)
s, it, _ = call("GET", "/scripts/interpreter")
check(
    "operator wheelhouse now listed",
    it["operator_wheelhouse"] in it["wheelhouses"],
    f"{it['wheelhouses']}",
)
print(f"\n{sum(checks)}/{len(checks)} passed")
raise SystemExit(len(checks) - sum(checks))
