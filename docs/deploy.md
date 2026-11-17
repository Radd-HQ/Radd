# Deploying Radd (spec 48)

One image runs everything: the API, the built web UI, and the background
workers. PostgreSQL 16+ is the only required service.

## The published image

Every release publishes an immutable image — pin a version, there is
deliberately no `latest` tag:

```bash
podman pull ghcr.io/radd-hq/radd:0.35.0     # anonymous pulls work
```

`compose.yaml` builds from source by default; to run the published image
instead, replace its `build:` block with `image: ghcr.io/radd-hq/radd:0.35.0`
(or `--set image.repository=ghcr.io/radd-hq/radd` under Helm). Each
release's SBOM and vulnerability report are attached to it on the releases
page.

## Compose (single node)

```bash
podman compose up -d          # db + app; app runs `alembic upgrade head` then serves
# http://localhost:8000  — create the first admin:
podman compose exec app python -m radd.seed --email you@example.com --password … --name "You"
```

The scripts plugin's managed interpreter lives on the same volume (`RADD_SCRIPTS_DIR=/data/scripts`). **It builds with no network** (RADD-1277): the image carries the Radd SDK and its dependency closure as wheels in `/app/wheels` (`RADD_SCRIPTS_FIND_LINKS`), and the build installs from there with uv held offline. Packages an admin adds resolve from the wheelhouses first, then the **package index named on Settings → Scripts** (empty = PyPI) — an air-gapped site points that at its mirror, or switches the interpreter **Offline** and drops wheels into `/data/scripts/wheels`, which is always searched. A rebuild for a Python the image lacks still needs uv to fetch one. `RADD_SCRIPTS_API_URL` is what a script's `ctx.client` calls; the chart sets it to the in-cluster Service so a worker-pod script does not hairpin through the ingress. Attachments live on the `radd-data` volume (`RADD_ATTACHMENTS_DIR=/data/attachments`)
by default. The `RADD_ATTACHMENT_STORAGE*` env settings only SEED the FIRST
storage-host row on first boot (spec 102) — afterwards Settings → Storage owns
storage entirely (multiple hosts, routing, delivery; Garage is the blessed
S3-compatible server, MinIO CE is archived — see "Multi-host storage" below).

**Behind a reverse proxy / ingress, set `RADD_TRUSTED_PROXIES`** to the proxy's
IPs or CIDRs (comma-separated, e.g. `10.42.0.0/16`). Radd only honors
`X-Forwarded-For` when the request's socket peer is in this list; unset, every
request appears to come from the proxy's address — which breaks storage CIDR
routing rules (spec 102) and any future IP-based feature. Never list ranges
end-users can occupy: a trusted peer's XFF is believed.

## First-run hardening

The compose defaults are tuned for a five-minute local trial. Before real
people sign in, walk this list — each item is one env var or one proxy block,
and every one of them fails **silently** if skipped:

1. **Change the database password.** The stack reads `RADD_DB_PASSWORD` (put it
   in a `.env` beside `compose.yaml`); the fallback `radd`/`radd` is public
   knowledge. Postgres's port 5455 is published to the host for dev
   convenience — firewall it or drop the `ports:` mapping from the `db`
   service in production.
2. **Terminate TLS in front and say so.** Run a reverse proxy (Caddy/nginx —
   worked example below) and set `RADD_SESSION_COOKIE_SECURE=true` so the
   session cookie refuses plaintext transport, plus `RADD_TRUSTED_PROXIES`
   as above so client IPs resolve through the proxy.
3. **Know that the MCP endpoint is ON by default.** `POST /api/v1/mcp` serves
   AI agents authenticating with the same PATs and RBAC as the REST API.
   That is a feature, not a hole — but if no agent will ever talk to this
   instance, disabling the `mcp` plugin (Settings → Plugins) removes the surface.
4. **Set the backup key and move it off-box.** First boot generates
   `radd-backup.key` beside the data dir; an encrypted backup and its key on
   the same disk is one failure, not a backup (see "Backup & restore").
5. **Seed the admin with a real password.** The seed command takes it on the
   CLI — use a throwaway shell history (`fish -P`, `HISTCONTROL=ignorespace`)
   or change it in Profile → Security immediately after first login.

### Response headers and the session cookie

Radd sets its own security headers on every response: `X-Content-Type-Options:
nosniff`, a referrer policy, frame protection (`frame-ancestors 'none'` and
`X-Frame-Options: DENY`), and `Strict-Transport-Security` when
`RADD_APP_BASE_URL` is https. Do not duplicate them at the proxy.

- **`RADD_FRAME_ANCESTORS`** (default `'none'`) is a CSP source list. Set it to an
  origin to let that site embed Radd in a frame.
- **`RADD_CSP_MODE`** is `report` by default: the browser logs what the
  Content-Security-Policy would block and blocks nothing. Once your browser
  console is clean on the screens you use (plugins, diagrams, attachments from
  object storage), set `enforce`. `off` removes the policy; framing stays protected.
- **The session cookie is `Secure` whenever `RADD_APP_BASE_URL` is https**, whether
  or not `RADD_SESSION_COOKIE_SECURE` is set. Setting the base URL correctly is
  therefore what protects the cookie; a wrong `http://` base URL behind TLS leaves
  it unprotected unless that variable is true.

## TLS in front (compose)

Radd itself speaks plain HTTP on :8000; TLS is the reverse proxy's job. The
smallest production-shaped front is Caddy on the same host — automatic
certificates, streaming pass-through, no body-size cap to tune:

```
# /etc/caddy/Caddyfile
radd.example.com {
    reverse_proxy localhost:8000
}
```

Then, in the `.env` beside `compose.yaml`:

```
RADD_SESSION_COOKIE_SECURE=true
RADD_TRUSTED_PROXIES=127.0.0.1        # where proxied requests arrive from
```

nginx works the same way — the two things it must do that Caddy does by
default: pass `X-Forwarded-For`/`X-Forwarded-Proto`, and raise
`client_max_body_size` (nginx caps request bodies at 1 MB out of the box,
which breaks attachment uploads; Caddy ships no cap). WebSockets
(`/api/v1/ws`) need the usual `Upgrade`/`Connection` header pass-through on
nginx; Caddy handles them automatically. Kubernetes deployments already
terminate TLS at their ingress — see `deploy/k3s/Caddyfile.chain.example`
for fronting an existing edge proxy.

## Upgrading (compose)

Migrations are **forward-only** and run automatically: the app container's
entrypoint is `alembic upgrade head && uvicorn …`, so an upgrade is:

```bash
podman compose exec app python -m radd.backup create   # or: verify last night's exists
git pull                                        # or edit the image tag you pin
podman compose build app                        # when building from source
podman compose up -d                            # recreates app; db keeps running
```

Three rules that keep this boring:

- **Backup before, every time.** `helm rollback`/re-running an old image does
  NOT reverse a migration — downgrade is *restore from backup*, never a
  schema rollback (same rule as the Kubernetes path below).
- **Don't skip more than a few releases at once** without reading their notes:
  migrations chain and are tested pairwise-adjacent, and release notes call
  out anything that needs an operator's hand.
- **Watch the migration finish** on big instances: `podman compose logs -f
  app` until uvicorn starts serving. The app refuses traffic until the
  schema converges, which is the correct failure mode.

### Upgrading from v0.52.0

Read these before the upgrade, not after; the release notes are generated from
commits and will not say them this plainly.

- **Check the server's PostgreSQL major first.** Until this release the image's
  client tools (17) could not restore a backup into a PostgreSQL 16 server:
  backups verified, and did not restore. Backups taken before the upgrade are
  restorable with the new image; take a fresh one after it anyway.
- **The database now remembers its encryption key.** The first start records
  the key it finds; a later start with a missing or different key file refuses
  to run rather than minting a new one. If the instance runs with attachments
  on S3 and the old chart, its key was on the pod's own disk: copy
  `/data/radd-backup.key` out BEFORE upgrading the chart, which now always
  mounts a volume there.
- **The upgrade takes longer on a large instance.** One migration folds the
  event ledger into a new table and holds a lock on issues while it does: about
  two minutes per million issue events (11 min 20 s on 5.0M), nothing
  noticeable on a few thousand issues. The app is down for that time.
- **`/timesheet` opens on "My week"**, a calendar for entering time. The grid
  it used to be is the **Report** tab; links with filters in them still open it.
- **A failed background handler is no longer silent.** Events a worker could
  not process are retried and then listed under Settings → Monitoring. An empty
  list is the normal state; a growing one is something that was being lost
  before.
- **Timesheet requests are bounded**: 366 days and 50,000 time logs. A wider
  request is refused with the reason. `GET /timesheet` callers that asked for
  years at once need a date range or a filter.
- **Webhooks and automation HTTP actions only call public addresses.** A
  webhook endpoint, a "Send webhook" or a "Post to chat" action pointing at a
  private, loopback or link-local address stops delivering after the upgrade:
  the delivery log says why, and saving such a URL is refused. If you send to an
  internal chat server or service, list it BEFORE upgrading:
  `RADD_OUTBOUND_ALLOWED_HOSTS=chat.internal.example,10.20.0.0/16` (hostnames
  and CIDRs).
- **A signed-in browser's writes must come from the instance's own address.**
  If people reach Radd under more than one address, or a proxy in front
  rewrites the `Host` header, set `RADD_APP_BASE_URL` to the address people use
  and list any others in `RADD_TRUSTED_ORIGINS`
  (`https://radd.example.com,https://radd.internal`). The symptom of getting
  this wrong is every save answering 403 with a message naming that setting.
  API tokens are not affected.
- **`PATCH /items/{id}` may answer 409** when it sends `description_version` and
  the description changed since. Callers that do not send it are unaffected.
- **Read notifications are deleted 90 days after they were read.** The first
  worker start after the upgrade removes every inbox notification that was
  read more than 90 days ago, and an hourly sweep keeps doing so. Unread ones
  are never deleted by age. Set `RADD_NOTIFY_READ_RETENTION_DAYS` to another
  period BEFORE upgrading if 90 is wrong for you; `0` keeps everything.
- **Responses are compressed by the app** (gzip, text responses of 1 KB or
  more; attachments, backups and sign-in routes are left alone). A proxy that
  already compresses passes them through. Nothing to set.
- **Permission lookups are cached per process** and dropped the moment a role,
  grant, membership, team or group changes (database triggers bump a counter
  every process reads). Access changes made by writing to the database directly
  are seen too. `RADD_AUTH_CACHE=false` turns it off if you ever suspect it.
- **Things people will notice on screen.** Lists show 50 rows a page (was 200;
  a chosen size is kept) and give the title more room. Board cards are as tall
  as their content, so they no longer line up in rows across columns. On an
  issue, the screen's fields sit directly under State, Type and Priority, and
  Visibility moved below them. My Work widgets shrink to their content. The
  cumulative-flow chart hides Done when it is over 80% of the total; click
  the legend to show it. The sidebar lists eight wiki spaces and a "Show all".
  Every date field is the app's own calendar: it shows the month spelled
  ("22 Nov 2026"), accepts typed dates, and looks the same in every browser.
  The Inbox has a **Clear read** button: it deletes the notifications a person
  has read (after asking), and unread ones stay. Each row also has its own
  clear button, which removes that notification, read or not, without asking.
  On a long list, rows far from view show only their key and title until
  scrolled near, so the browser's find-in-page does not match their labels or
  assignee.

### Upgrading from v0.49.3

Nothing switches off. Two migrations change rows you may notice:

- `d1492subtaskhome` — a subtask now lives in its parent's project (RADD-1492). Any subtask whose
  parent issue sits in another project becomes a top-level **issue** in its own project, and the
  migrate job's log prints the keys it converted. Re-parent or link them as you see fit; nothing is
  lost.
- `d1481leavetime` — leave periods gain boundary times and a zone (RADD-1481). Existing rows stay
  all-day and are read as UTC; no action needed.

### Upgrading from v0.48.0

The first release after v0.48.0 (the v0.49 line) moves several built-in behaviours behind switches that migrate **off** for
existing rows (the integration-settings decision of RADD-1367: integrations record
data and fire triggers; a behaviour is something an admin switched on). Nothing breaks,
but each of these stops until it is switched back on, and the release notes are
generated from commits, so this list is the operator's record:

| Stops after upgrade | Where to switch it back on |
|---|---|
| Publishing a Radd version and sweeping issues to Done when a GitHub/GitLab/Forgejo release is published | Settings → Version control → the repository row → **Publish a version on release** |
| Moving merged issues to the project's waiting-for-release state | Same row → **Move merged issues to waiting** |
| Mirroring VCS time entries into worklogs | Same row → **Mirror time** |
| The receipt mailed to a reporter when an emailed ticket is created, and the resolution notice | Settings → Email → **Automatic messages** (`mail_send_ack`, `mail_send_resolved`; a custom receipt body is kept) |
| Notification mail on an instance that set `RADD_SMTP_*` but has the **mailintake** plugin disabled | Enable mailintake (the notify module no longer carries its own SMTP fallback); notifications that found no transport are recorded as undeliverable, not sent |

Two of this release's migrations cannot be downgraded (`d1329verdict` rewrites
automation graphs into verdict nodes; `d1334review` scopes VCS data per
connection) — `alembic downgrade` refuses with a message. Rolling back this
release means restoring the backup you took first, as the rule above says.

## Sizing

Measured, not estimated: `docs/performance.md` has the 200-user load test these
rows come from (RADD-1536), with what it did and did not cover.

**One web process serves about 20 requests a second**, whatever the database
can do: it is one event loop, and a request costs 25 to 50 ms of Python. That
is roughly 50 people working at once. Past that, run more web processes beside
one worker (`web.processes` and `workers.enabled` in the chart).

| Instance | Web | Worker | Postgres | Disk |
|---|---|---|---|---|
| Trial / small team (≤25 people, ≤50k items) | 1 process, 1 vCPU, 512 MB | same process | 1 vCPU, 1 GB, `shm_size: 1g` | 10 GB + attachments |
| Team (≤50 people working at once, ≤250k items) | 1 process, 1 vCPU, 1 GB | same process | 2 vCPU, 4 GB | 50 GB + attachments |
| Heavy (200 working at once, 500k items, 5M events: measured) | 4 processes, 3 vCPU, 2 GB | 1 pod, 1 vCPU, 512 MB | 6 vCPU, 8 GB, `max_connections` ≥ 100 | 100 GB+ + attachments |

The database connection pool is `RADD_DB_POOL_SIZE` (5) plus
`RADD_DB_MAX_OVERFLOW` (10) **per process**: four web processes and a worker can
hold 75 connections. A request waits `RADD_DB_POOL_TIMEOUT_SECONDS` (30) for one
and is then answered 503 with `Retry-After`. A request's statements are
cancelled after `RADD_DB_STATEMENT_TIMEOUT_SECONDS` (30, `0` disables) and
answered with a 504 that says so; imports, backfills and the background loops
are not bound by it.

A timesheet request covers at most `RADD_TIMESHEET_MAX_RANGE_DAYS` (366) and
`RADD_TIMESHEET_MAX_ENTRIES` (50,000) time logs; past either it is refused with
the reason, never truncated.

Notes that matter more than the table: **attachments dominate disk** (budget
them separately; S3-mode moves them off-box); **semantic search** adds
pgvector index memory and — with the built-in CPU embedder — slow bulk
indexing (~20 texts/s: fine incrementally, hours for a 500k-item backfill;
use a GPU TEI for bulk); backups need headroom for one full artifact beside
the data.

## Monitoring

Radd is observable from outside the app. Set these and point a scraper at it:

| Variable | Default | What it does |
|---|---|---|
| `RADD_LOG_FORMAT` | `text` | `json` writes one object per line, with the request ID and any structured fields |
| `RADD_METRICS_ENABLED` | `false` | serves `/metrics` in the Prometheus text format |
| `RADD_METRICS_TOKEN` | empty | when set, a scraper must send `Authorization: Bearer <token>` |

Every response carries `X-Request-ID` (a proxy's own ID is kept when it sends
one). Search the logs for it: every line written while serving that request has
it, including errors reported from the browser (`radd.client_error`).

Two probes: **`/health`** for liveness (it does not ask the database, on purpose:
restarting a pod does not bring a database back) and **`/ready`** for readiness
(it does, and answers 503 without one).

What `/metrics` exposes, and the alerts worth having:

| Series | Alert when |
|---|---|
| `radd_http_requests_total{route,status}` | the share of `5xx` rises |
| `radd_http_request_duration_seconds` (histogram, by route) | p95 for a route you care about passes your budget |
| `radd_event_loop_lag_seconds` | above ~0.5 for minutes: something is blocking the one event loop |
| `radd_db_pool_connections{state}` | `in_use` sits at pool size plus overflow |
| `radd_consumer_lag_events{consumer}`, `radd_consumer_seconds_since_progress` | lag grows while the cursor does not move: notifications, webhooks, automations or search are behind. A long-running import holds consumers back until it commits; that shows here |
| `radd_consumer_failed_events{consumer,status}` | `status="dead"` above zero: a handler gave up on an event; look at Settings → Monitoring |
| `radd_backup_age_seconds` | older than twice your schedule's interval |

Also alert, outside Radd, on the instance answering at all and on the
certificate's expiry at the ingress: both have taken an instance down, and both
times a user noticed first.

Metrics are per process. With the worker split on, scrape both pods.

## One worker, several web processes

**The background loops run in exactly one process.** Mail polling, directory
sync, the mailers, schedules and the SLA clock are not written to run twice.
Event consumers themselves claim their cursor per tick since RADD-1538, so two
of them would not double-deliver, but that is a safety net, not a licence.

**The web tier can be several processes** (`web.processes` in the chart, with
`workers.enabled=true`). Each tails the event stream for its own realtime
sockets, plugin state converges through the lease table, and the measured
effect is in `docs/performance.md`. Three things are per process and stay that
way: the login and write throttles (a limit of N becomes up to N times the
process count), `/metrics` (each process answers with its own numbers), and
co-editing rooms, below.

A failed handler in a consumer is no longer a lost side effect: the event is
recorded, retried with backoff, and listed under **Settings → Monitoring →
Failed events** when it runs out of attempts, where it can be replayed or
discarded. `radd_consumer_failed_events{status="dead"}` above zero is worth an
alert.

**Collaborative editing (spec 122) sharpens that rule.** A wiki page being
co-edited is a room held in the API process's memory (`radd.modules.collab`):
the Yjs document, who is connected, the seed grant, the debounced write to
`page_collab_docs`. Every editor of one page must reach the SAME process, so
with more than one API replica the whole of `/api/v1/collab/*` — the join and
the WebSocket — needs sticky routing to one replica, or a shared relay in front
of the rooms. The chart does the first: with `workers.enabled=true` its Ingress
sends `/api/v1/collab` to the single worker pod (RADD-1544). A proxy of your own
must do the same. That routing has been rendered and reviewed, not yet run on a
cluster: check two browsers on one page after turning it on. The stored
state survives a restart (a room resumes it when its `page_version` still
matches the page's), so a rollout costs editors a reconnect, not their work.

## Multi-host storage (spec 102)

The env storage settings above SEED one host row on first boot; afterwards
Settings → Storage owns everything: several S3 deployments + filesystem roots
at once, an ordered routing chain (user choice / CIDR / LLM), per-host
delivery. **Garage** (https://garagehq.deuxfleurs.fr) is the blessed
S3-compatible server — MinIO's community edition was archived in Feb 2026; any
S3-compatible endpoint works.

- **Zoned/air-gapped hosts**: give the host `presigned` delivery. Presigning is
  offline crypto — the API mints URLs it could never fetch itself, and only
  browsers whose network can route to the host can use them. Never configure a
  zoned host as `proxy` (the API would tunnel its bytes out of the zone); the
  host form warns.
- **Region matters**: Garage rejects signatures whose scope names another
  region (`AuthorizationHeaderMalformed … unexpected scope`). Set the host's
  region to the server's `s3_region` — `garage` in the bundled dev config.
- Dev walkthrough: `podman compose -f compose.dev.yaml --profile storage up -d`
  (two Garage hosts on `localhost:3900`/`3910`), then
  `sh deploy/garage/init.sh garage-1` — endpoint/bucket/key values to paste
  into Settings → Storage are printed in that script's header.
- Deleting an attachment (or its parent item/wiki page) now removes the BYTES
  too, via the `attachments.gc` consumer; hosts with attachments can't be
  deleted — use the per-host "Move all to…" job first.

## Semantic search (spec 103)

Needs the **pgvector** extension in Postgres: the bundled compose files run
`pgvector/pgvector:pg16` (a drop-in postgres:16 superset — existing volumes
keep working; REINDEX once if you switch from the alpine image, the libc
collation differs). External DB: install pgvector and `CREATE EXTENSION
vector;` as superuser, then restart Radd — the embeddings schema is created at
startup, no re-migration.

**Embedding model — no external server needed**: the container image ships the
`radd[localembed]` extra (fastembed: ONNX on CPU, no GPU/torch). In Settings →
AI add a provider with wire shape **Built-in (CPU embeddings)** and assign it
the embeddings role — done. Weights (~30–130 MB) download from Hugging Face on
first use into `RADD_AI_LOCAL_EMBED_CACHE` (default `var/models`); **pre-seed
that directory on air-gapped deploys**. Default model `BAAI/bge-small-en-v1.5`
(384d); `GET /ai/local-embed` lists alternatives (multilingual included). The
built-in backend is the zero-infra FALLBACK tier — ~20 texts/s on a desktop
CPU, fine for small instances, slow for bulk imports (500k items ≈ 7 h).

**Big corpus or a GPU? Run the optional `embeddings` compose service** (Hugging
Face text-embeddings-inference) and keep model serving out of the app process:
`--profile embeddings` (CPU image) or `--profile embeddings-gpu` (CUDA image —
needs `nvidia-container-toolkit` + `nvidia-ctk cdi generate` on the host; the
compose file pins the `86-*` tag for compute capability 8.6 = RTX 30xx/A10;
swap for `:1.9` sm80/A100, `:89-1.9` Ada, `:hopper-1.9` H100, `:turing-1.9`
older cards). Then Settings → AI: an ordinary **OpenAI-shape provider**,
base_url `http://embeddings/v1` (containerized app; `http://localhost:8081/v1`
from a host-run dev server), model `BAAI/bge-small-en-v1.5`, holding the
embeddings role. Serving the SAME model the built-in backend used keeps
already-embedded vectors valid — no re-embed on switch-over (measured on an
RTX 3080: ~2,000 texts/s vs ~20 CPU). `RADD_EMBEDDINGS_MODEL` /
`RADD_EMBEDDINGS_PORT` override the model and host port.
Alternatively point the provider at any other `/v1/embeddings` server
(EmbeddingGemma / `nomic-embed-text` on Ollama, vLLM `--task embed`). Either
way the backfill runs itself and Settings → AI shows coverage. Without any of
this, search stays plain FTS — nothing breaks.

## Development (code mounted in the container)

```bash
podman compose -f compose.dev.yaml up      # db + API on :8000, live reload
cd web && npm run build                    # or `npm run dev` on :5173
```

`./server` is bind-mounted over `/app/server`, so edits reload immediately, and
the container brings the tools the app REQUIRES (`pg_dump`/`pg_restore`) without
installing a Postgres client on your machine. The venv lives at `/opt/venv`,
outside the mount, so it is not shadowed; the project is installed editable, so
the mounted source is what runs.

It builds `--target dev`, which skips the SPA stage entirely — no npm during the
image build. `web/dist` is mounted instead.

**Corporate/split DNS.** Podman's internal resolver forwards to the HOST's
`/etc/resolv.conf`, which under systemd-resolved is the `127.0.0.53` stub — a
loopback address the container cannot reach. Routing to internal networks works;
only NAME RESOLUTION fails, so LDAP/Jira/GitLab hostnames come back as
`invalid server address` while the same code works host-run. Put your real
resolvers in a gitignored root `.env`:

```
RADD_DEV_DNS=10.0.0.2
```

Podman keeps its own DNS for compose service discovery alongside it, so `db`
still resolves. Check with
`podman exec radd-dev_app_1 getent hosts your.ad.example.com`.

Its own compose project name (`radd-dev`) keeps it from colliding with
`compose.yaml`'s containers; `RADD_DEV_PORT` / `RADD_DEV_DB_PORT` move the
published ports if both stacks run at once. Artifacts and the backup key land in
`./var/` (gitignored) so they can be inspected from the host.

## Kubernetes (Helm)

> Single-node k3s walkthrough with sample configs: **`docs/deploy-k3s.md`** +
> `deploy/k3s/` (CloudNativePG, pgvector, backup storage class, proxy chain).

```bash
podman build -t registry.example.com/radd:0.33.0 -f Containerfile .
podman push registry.example.com/radd:0.33.0
helm install radd deploy/helm/radd \
  --set image.repository=registry.example.com/radd --set image.tag=0.33.0 \
  --set env.RADD_DATABASE_URL=postgresql+psycopg://radd:…@pg:5432/radd \
  --set env.RADD_APP_BASE_URL=https://radd.example.com \
  --set ingress.enabled=true --set ingress.host=radd.example.com
```

A tag only reaches the registry after `.github/workflows/publish.yaml`'s
`test` job goes green — `uv run pytest` against a throwaway Postgres, `tsc -b`,
`vite build` — which the `image` job `needs:` (RADD-1037; before this, a tag
shipped whatever the commit contained, untested). Both jobs run in the pinned
`ci-runner` image (`deploy/ci-runner.Containerfile`), so the gate needs no
network access beyond the registries CI already reaches.

Every release on the canonical repo (`github.com/radd-hq/radd`) ships with two
CycloneDX SBOMs as release assets: `radd-<version>-image.cdx.json` describes the
container image (Debian packages, the installed Python environment, and what
syft reads out of embedded binaries), and `radd-<version>-web.cdx.json` the npm
tree the web bundle was built from — the bundle itself is minified, so the image
scan alone cannot see the frontend's dependencies. Feed them to whatever
consumes CycloneDX (grype, Dependency-Track, OSV) — or read them: the same two
documents are rendered as one wiki page per version (`SBOM <version>`, a child
of that version's release-notes page, `scripts/sbom_page.py`), so "do we still
ship that crate?" is a browser find rather than a jq expression (RADD-1065).
Next to them sit the trivy
vulnerability reports for the same two targets (`radd-<version>-image-vulns.json`,
`radd-<version>-web-vulns.json`), generated at tag time — report-only, since most
base-image CVEs have no fixed package to move to; a rebuilt image on the same
tag (workflow_dispatch) is how a fixable one gets picked up.

- Migrations run as a pre-install/pre-upgrade hook Job.
- Secrets (SMTP, OIDC/LDAP, S3, AI keys) go in a Secret referenced by
  `envFromSecret` — never in plain values.
- **Two PVCs, and both matter.** `-data` holds attachments plus the backup
  encryption KEY; `-backups` (`backups.enabled`, default on) holds the
  artifacts. They are separate so one lost volume can't take both — put
  `backups.storageClassName` on a different disk from the database. Both the
  web and worker pods mount both: the nightly dump runs wherever
  `RADD_RUN_WORKERS` is true (the worker, once split), while restores are
  driven from the web tier. On multi-node you need RWX or node affinity —
  these claims are RWO.
- `podSecurityContext.fsGroup: 10001` is set by default, matching the image's
  `USER radd`. Without it the volumes mount root-owned and the app cannot
  write attachments or backups.
- `imagePullSecrets: []` for a private registry (a Forgejo/Gitea package
  registry, say) — applied to web, worker, and the migration Job.
- **Worker split**: `--set workers.enabled=true` gives web replicas
  `RADD_RUN_WORKERS=false` and adds ONE worker pod running the loops
  (webhooks, automations, notifications/email, search indexing, SLA clock,
  connectors). Keep `workers.replicas: 1`: the pollers and mailers are not
  written to run twice. `--set web.processes=4` then runs four web processes
  in the web pod (see Sizing); the Ingress routes co-editing to the worker.
- Probes hit `GET /api/v1/instance/login-options` (unauthenticated).

## Backup & restore

Radd backs itself up (spec 99). A **nightly schedule is seeded on first boot**
(03:00, keep 7, attachments included) — there is nothing to switch on. Manage it
at **Settings → Backups**, or from a shell:

```bash
uv run python -m radd.backup status                 # directory, tools, key
uv run python -m radd.backup create                 # take one now
uv run python -m radd.backup list
uv run python -m radd.backup restore <name> [--yes] # REPLACES everything
```

The CLI matters: after a total loss there is no running app to click a button
in, so restoring onto a fresh, empty database is a shell operation.

**Artifacts** land in `RADD_BACKUP_DIR` (default `/opt/radd/backups`) as
`radd-<timestamp>-<id>.radd` — a plaintext manifest header followed by an
**AES-256-GCM** payload holding `pg_dump -Fc` output plus the attachments tree.
Every finished artifact is verified (`pg_restore --list`) before it counts.

### The key

**`RADD_BACKUP_KEY_FILE` (default `/data/radd-backup.key`) is generated on first
use and must be backed up separately from the backups themselves.** Without it
every artifact is unrecoverable — that separation is the point: one stolen
volume yields either the ciphertext or the key, never both. Set
`RADD_BACKUP_ENCRYPTION=false` only if the filesystem is already encrypted.

The same key encrypts the credentials stored in the database (webhook secrets,
SSO, mail, AI and connector tokens), so **the database records which key it was
written with, and Radd refuses to start if the key file is missing or is a
different key.** A missing file on a running instance means a lost or unmounted
volume, not a first boot; a freshly minted key would start cleanly and decrypt
nothing. The message names the key it expects.

- **Restoring onto a new host:** put the original key file in place before the
  first start.
- **The key is gone for good:** start once with `RADD_BACKUP_KEY_ADOPT=true`.
  The present key is recorded instead; every backup and stored credential from
  before is unreadable and the credentials must be entered again. Unset it
  afterwards.
- **Helm:** the `-data` volume holding the key exists in every storage mode. With
  `storage.s3=true` it is `storage.stateSize` (1Gi) instead of absent — before
  RADD-1525 an S3 deployment kept the key on the pod's ephemeral layer. If you
  ran one, copy the key off the pod (`kubectl cp`) BEFORE upgrading the chart,
  and put it on the new volume.

### Two prerequisites

- **`pg_dump`, `pg_restore` and `psql` are required** — the app refuses to start
  without them. The image (Debian trixie) ships `postgresql-client-17`, which
  carries all three; the client major must be **≥** the server's. A client NEWER
  than the server is supported in both directions: before RADD-1543 a 17 client
  could back up a 16 server but could not restore into it (the archive carried a
  session setting 16 does not know, and the restore aborted). **If you run
  PostgreSQL 16 on a release older than that fix, your backups verify and do not
  restore** — upgrade, then prove it with a restore into a scratch database.
  Only a host-run dev server needs `RADD_BACKUP_TOOLS_OPTIONAL=true`;
  `compose.dev.yaml` runs in the container where the tools already exist.
- **Put `RADD_BACKUP_DIR` on a different disk from the database.** A backup that
  dies with the volume it protects is not a backup. For a bind mount, chown it to
  the container user first: `sudo chown 10001:10001 ./backups` (Kubernetes:
  `podSecurityContext.fsGroup: 10001`).

### Restoring

From the UI, a restore takes a **safety backup first**, puts the instance into
maintenance mode (503 everywhere but the backup status endpoint), drops and
reloads the schema, runs `alembic upgrade head`, and extracts attachments over
the existing tree. If it fails it rolls back to the safety backup; if that also
fails maintenance stays engaged, because a half-restored Radd must not serve
traffic. **Restore is single-node — scale replicas to 1 first.**

Two things are NOT in an artifact and still need your attention:

- **The backup key** (above).
- **Environment/secrets** — the `RADD_*` env (webhook signing secrets,
  OIDC/LDAP/AI credentials). These live outside the database by design.
- **S3-stored attachments**, when `RADD_ATTACHMENT_STORAGE=s3` — the bucket has
  its own lifecycle and versioning; artifacts then carry the database only.

Consumer offsets restore with the database, so webhooks/notifications resume
from where the dump was taken — consumers are at-least-once by design, so
duplicates after a restore are possible and harmless.

**Recovering without Radd**, if you ever need to: the artifact is a header plus
an encrypted tar, so `python -m radd.backup restore` is the supported path. With
`RADD_BACKUP_ENCRYPTION=false` the payload is a plain tar containing
`database.dump`, restorable with `pg_restore` directly.

## Email service desk (RADD-951 wave)

**Radd never terminates a mail protocol.** It reads a mailbox and hands messages
to a relay; a hosted provider does the rest.

The radd-hq.com deployment runs on **Migadu**, with three mailboxes:

| mailbox | role |
|---|---|
| `help@radd-hq.com` | ticket intake — Radd POLLS this over IMAP |
| `agent@radd-hq.com` | the identity Radd SENDS as (`RADD_SMTP_FROM`) |
| `git@radd-hq.com` | Forgejo's own notifications; nothing to do with Radd |

```
customer ──▶ help@ (Migadu)  ──IMAP 993──▶ Radd poller ──▶ issue / comment
Radd ──SMTP 587──▶ Migadu ──▶ participants     From: agent@   Reply-To: help@
```

**Why polling rather than a push webhook here.** The ISP drops port 25 in both
directions, so this host cannot receive SMTP — which is what the original design
routed around with Cloudflare Email Routing and an HTTPS Worker. IMAP was never
blocked by that: it is an *outbound* connection on 993. With a real mailbox the
poller is simply fewer moving parts, and since RADD-951 it runs through the same
`intake.accept` core as the webhook, so it inherits threading, dedup, quote
stripping, attachments and the loop guards.

`POST /api/v1/integrations/email` remains for push sources (a Gmail adapter, or
a Worker if one is ever wanted). The secret it verifies is the matching mail
source row's; with no row and `RADD_EMAIL_INGEST_SECRET` unset it **rejects every
request** — an unused endpoint is a closed one.

**Mail is configured in Settings → Email** (sources, senders, routing — RADD-958).
The variables below are **seed-only**: on a database with no mail rows they create
the first source and sender, once, and are not read for configuration again
(`mailintake/seeding.py`); the SMTP and ingest-secret values also stand in while no
row exists yet. Their traps still apply to the rows they seed:

| variable | value here | why it matters |
|---|---|---|
| `RADD_MAIL_IMAP_HOST/PORT/USERNAME/PASSWORD` | Migadu, `help@` | seeds the first IMAP source; unset seeds nothing — intake then runs from whatever sources Settings → Email holds |
| `RADD_MAIL_PROJECT_KEY` | a real project key | the seeded source's default project (and the webhook's fallback); naming no project makes every new ticket fail — the webhook answers 503 rather than bouncing the sender |
| `RADD_SMTP_FROM` | `Radd <agent@radd-hq.com>` | the seeded sender's From, and part of the self-loop guard — mail from any sender's address arriving at a source is dropped |
| `RADD_EMAIL_INGEST_ADDRESS` | `help@radd-hq.com` | the seeded source's address and sender's `Reply-To`, and the other half of the loop guard |

Plain `help@`, deliberately not `help+token@`: sub-addressing is rewritten or
stripped by exactly the corporate mail systems this feature targets, which is
why threading matches on `In-Reply-To`/`References` instead (RADD-954).

## Environment reference (the load-bearing subset)

Every setting lives in `server/src/radd/config.py` (env prefix `RADD_`,
`.env` supported) — that file is the authoritative list. **Seed-only** below means
the value creates the first database row on an empty instance, once; after that the
named Settings page owns it and editing the variable changes nothing. Highlights:

| Variable | Default | Purpose |
|---|---|---|
| `RADD_DATABASE_URL` | localhost dev DB | SQLAlchemy Postgres URL (required in prod) |
| `RADD_APP_BASE_URL` | `http://localhost:8000` | absolute links in emails/connectors |
| `RADD_SCRIPTS_FIND_LINKS` / `RADD_SCRIPTS_API_URL` | `/app/wheels` (image) / `RADD_APP_BASE_URL` | script interpreter wheelhouses; the URL scripts call back (RADD-1277) |
| `RADD_SESSION_COOKIE_SECURE` | `false` | set `true` behind HTTPS |
| `RADD_RUN_WORKERS` | `true` | `false` = web-only process (worker split) |
| `RADD_WEB_DIST` | repo `web/dist` | built SPA to serve |
| `RADD_MODULES` | all | ordered module assembly (the plugin system) |
| `RADD_ATTACHMENT_STORAGE` / `RADD_S3_*` | filesystem | **seed-only** → Settings → Storage: the first storage host (spec 102) |
| `RADD_SMTP_*` | disabled | **seed-only** → Settings → Email: the first outbound sender (digests, acks, comment replies); used directly only while no sender row exists |
| `RADD_EMAIL_INGEST_SECRET` | disabled | **seed-only** → Settings → Email: the first webhook source's HMAC for `POST /integrations/email`; the fallback while no source row exists. **Empty rejects everything** |
| `RADD_OIDC_*` | disabled | **seed-only** → Settings → Sign-in: the first SSO provider (spec 110) |
| `RADD_LDAP_*` | disabled | **seed-only** → Settings → Directory: the AD connection and sync tunables (spec 42, RADD-846/848) |
| `RADD_AI_*` | disabled | provider/base URL/key/model are **seed-only** → Settings → AI (spec 101); `_MAX_TOKENS` and the timeouts stay live |
| `RADD_GITLAB_*` / `RADD_FORGEJO_*` / `RADD_GITHUB_*` | disabled | **seed-only** → Settings → Version control: each seeds one connection (and repository) once; `_API_TOKEN`, `_BASE_URL`, `_REPO` optional |
| `RADD_ALERTMANAGER_*` / `RADD_MAIL_*` | disabled | seed ONE Alertmanager receiver / mail source row, once (RADD-1317, RADD-958) — both are configured in Settings after. `RADD_GOOGLECHAT_*` is gone (RADD-1319): posting to chat is an automation |
| `RADD_WORK_WEEK_DAYS` | mon–fri | business-day SLAs + timesheet |
| `RADD_NOTIFY_READ_RETENTION_DAYS` | `90` | inbox notifications are deleted this long after they were read (RADD-1570); `0` keeps everything. `RADD_NOTIFY_RETENTION_INTERVAL` (3600 s) and `RADD_NOTIFY_RETENTION_BATCH` (5000) pace the sweep |
| `RADD_AUTH_CACHE` | `true` | per-process cache of role/grant/membership lookups, invalidated by database triggers (RADD-1560); `false` reads them every request |
| `RADD_DB_FORCE_CUSTOM_PLANS` | `true` | plans each statement for its actual values; without it the board's reads degraded from 15 ms to 400 ms after five runs (RADD-1545) |
| `RADD_BATCH_MAX_REQUESTS` | `30` | how many GETs one `POST /api/v1/batch` may carry (RADD-1561) |
| `RADD_AI_EMBED_IDLE_SWEEP_MAX_SECONDS` | `300` | the embedder's longest wait between sweeps when there is nothing to embed (RADD-1550) |

## Reviewing imported Jira comment audiences

A read-only report of how imported Jira comments' audiences compare with their
source (RADD-1182). From `server/`, with `RADD_DATABASE_URL` pointing at the
instance:

```bash
.venv/bin/python -m radd.modules.jiraimport.audit_comments > comment-visibility-review.jsonl
# Optional: limit to exact import runs (repeat --run-id).
.venv/bin/python -m radd.modules.jiraimport.audit_comments --run-id RUN_UUID > run-review.jsonl
```

It runs in a READ ONLY, REPEATABLE READ transaction, has no apply option, and
prints JSONL (scope, findings, summary) without comment bodies, emails or
credentials — but with IDs and source audience names, so keep it with operator
records. Findings join on each creation record's exact run, snapshot, issue key
and comment ID, never on matching text; imports without provenance records are
outside its coverage, so a clean report certifies nothing about them.

| Action | Meaning and next step |
|---|---|
| `make_internal` | The snapshot marks an internal note but the target is public. Back up, then correct the visibility explicitly. |
| `review_restricted_audience` | The snapshot names a Jira role/group. Agree the intended Radd audience; internal alone is not equivalent. |
| `source_unavailable` | The snapshot or source comment is missing. Reconcile with the source or a backup; this is not a safe result. |
| `target_missing` | The ledger target no longer exists. Do not recreate it automatically. |
| `no_change_indicated` | Nothing indicates a change; counted in the summary only. |

Before any repair: keep a backup and the before-state, apply corrections through
the normal comment service, then recheck REST, search, notifications and history
as both permitted and excluded users.

## MFA (TOTP)

Local-password accounts can enroll TOTP from their profile
(`POST /auth/totp/setup` → secret + `otpauth://` URI → confirm with a code).
Once enabled, `POST /auth/login` answers `401 {"detail":"totp_required"}`
and the client completes via `POST /auth/login/totp`. SSO/LDAP sign-ins are
untouched — the IdP owns MFA there. **Recovery is self-service (RADD-677):**
confirming enrollment hands the user ten single-use recovery codes (shown
once, stored hashed); any of them works wherever the 6-digit code does —
sign-in, disable, regenerate — and burns on use. The admin fallback (clearing
the user's `user_totp` row) remains for the person who lost the phone AND the
printout.


## What the server will call, and who may call it

Two guards, both on by default.

**Outbound requests** (`RADD_OUTBOUND_ALLOWED_HOSTS`). Webhook endpoints and the
automation HTTP actions call a URL a user typed. They are only sent to public
addresses: loopback, private ranges and link-local (the cloud metadata range)
are refused when the URL is saved and again when the name is resolved, and the
request goes to the address that was checked. Redirects are not followed. To
allow internal targets, list hostnames and CIDRs. The connectors an instance
admin configures (version control, SSO, AI, imports, storage) are not subject
to this: naming internal services is what those settings are for.

**Request origin** (`RADD_TRUSTED_ORIGINS`, `RADD_ORIGIN_CHECK`). A write or a
WebSocket handshake that carries the session cookie must come from the
instance's own origin: the request's own host, `RADD_APP_BASE_URL`, or a listed
origin. Requests with an `Authorization` header and clients that send no
browser headers are not checked. `RADD_ORIGIN_CHECK=false` turns it off; do
that only to diagnose.

## Login and realtime limits

Password login admission is enforced in the web process, shared by local, TOTP and LDAP sign-in. Defaults: `RADD_AUTH_LOGIN_ACCOUNT_ATTEMPTS=20`, `RADD_AUTH_LOGIN_IP_ATTEMPTS=120`, `RADD_AUTH_LOGIN_WINDOW_SECONDS=300`, and at most `RADD_AUTH_LOGIN_BUCKET_LIMIT=10000` retained account/IP buckets. Attempts beyond the limits return HTTP 429 with `Retry-After`. These counters follow the documented single-web-process deployment; multiple workers or replicas require a shared admission store or equivalent ingress controls. Configure the existing trusted-proxy chain correctly so the client-IP resolver distinguishes users behind your proxy.

Issue and comment creation carry a per-account sliding window (spec 121 §9 — open sign-up on a public instance needs a bounded write rate): `RADD_ITEM_CREATES_PER_WINDOW=30` and `RADD_COMMENTS_PER_WINDOW=120` per `RADD_WRITE_WINDOW_SECONDS=3600`, at most `RADD_WRITE_THROTTLE_BUCKET_LIMIT=10000` retained (bucket, account) counters. Writes beyond the limit return HTTP 429 with `Retry-After`. Instance admins and the automation actor are exempt; service-account keys count against their account. The same single-process caveat applies.

`RADD_AUTH_PASSWORD_WORKERS=4` bounds concurrent Argon2 jobs off the event loop. Realtime defaults to `RADD_REALTIME_SEND_TIMEOUT=2` seconds, `RADD_REALTIME_SEND_CONCURRENCY=32`, and `RADD_REALTIME_SESSION_REFRESH_SECONDS=60`. Unhealthy sockets disconnect and clients refetch after reconnect. The realtime protocol accepts active-query interests with explicit project filters, validates their access, and sends only cache invalidation hints.

API keys cannot mint personal or service-account credentials. Manage credentials in a browser session. Privileged instance operations still require an instance-admin account, and a scoped key must also explicitly permit `global.manage` to use that administrative bypass. Ordinary project permissions continue to be intersected with the key's scope.

## Uploaded plugin storage

The image uses `RADD_PLUGINS_DIR=/data/plugins`. Web and worker processes must
share that persistent directory. The Helm chart creates a dedicated plugin PVC;
`plugins.size`, `plugins.storageClassName` and `plugins.accessMode` control it.
The default ReadWriteOnce mode requires compatible placement; use a ReadWriteMany
class for multi-node replicas. The filesystem must support advisory locks and
atomic rename. Back up this volume along with the database and retain release
wheels separately. S3 attachment storage does not replace the plugin volume.

Uploaded pure-Python packages need no custom RADD image if their dependencies
already exist. UI-only manifests can activate live; backend hooks/routes/tasks
still need process restarts. See [managed plugin packages](specs/127-managed-plugin-packages.md).
