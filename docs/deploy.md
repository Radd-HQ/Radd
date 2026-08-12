# Deploying Radd (spec 48)

One image runs everything: the API, the built web UI, and the background
workers. PostgreSQL 16+ is the only required service.

## Compose (single node)

```bash
podman compose up -d          # db + app; app runs `alembic upgrade head` then serves
# http://localhost:8000  — create the first admin:
podman compose exec app python -m radd.seed --email you@example.com --password … --name "You"
```

Attachments live on the `radd-data` volume (`RADD_ATTACHMENTS_DIR=/data/attachments`)
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
podman build -t registry.example.com/radd:0.1.0 -f Containerfile .
podman push registry.example.com/radd:0.1.0
helm install radd deploy/helm/radd \
  --set image.repository=registry.example.com/radd --set image.tag=0.1.0 \
  --set env.RADD_DATABASE_URL=postgresql+psycopg://radd:…@pg:5432/radd \
  --set env.RADD_APP_BASE_URL=https://radd.example.com \
  --set ingress.enabled=true --set ingress.host=radd.example.com
```

A tag only reaches the registry after `.forgejo/workflows/publish.yaml`'s
`test` job goes green — `uv run pytest` against a throwaway Postgres, `tsc -b`,
`vite build` — which the `image` job `needs:` (RADD-1037; before this, a tag
shipped whatever the commit contained, untested). Both jobs run in the pinned
`ci-runner` image (`deploy/ci-runner.Containerfile`), so the gate needs no
network access beyond the registries CI already reaches.

Every release on the canonical repo (`git.radd-hq.com/Radd/Radd`) ships with two
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
  connectors). Keep `workers.replicas: 1` — consumers are single-writer by
  design (per-consumer offsets); scale beyond that means NATS per the plan.
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

### Two prerequisites

- **`pg_dump`/`pg_restore` are required** — the app refuses to start without
  them. The image (Debian trixie) ships `postgresql-client-17`; the client major
  must be **≥** the server's. Only a host-run dev server needs
  `RADD_BACKUP_TOOLS_OPTIONAL=true`; `compose.dev.yaml` runs in the container
  where the tools already exist.
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
a Worker if one is ever wanted). With `RADD_EMAIL_INGEST_SECRET` unset it
**rejects every request** — an unused endpoint is a closed one.

Settings that matter, and the trap in each:

| variable | value here | why it matters |
|---|---|---|
| `RADD_MAIL_IMAP_HOST/PORT/USERNAME/PASSWORD` | Migadu, `help@` | unset host = intake is off entirely |
| `RADD_MAIL_PROJECT_KEY` | a real project key | naming no project makes every new ticket fail; the webhook answers 503 rather than bouncing the sender |
| `RADD_SMTP_FROM` | `Radd <agent@radd-hq.com>` | also the self-loop guard's comparison — mail from this address arriving in `help@` is dropped |
| `RADD_EMAIL_INGEST_ADDRESS` | `help@radd-hq.com` | the `Reply-To` on every outbound message, and the second half of the loop guard |

Plain `help@`, deliberately not `help+token@`: sub-addressing is rewritten or
stripped by exactly the corporate mail systems this feature targets, which is
why threading matches on `In-Reply-To`/`References` instead (RADD-954).

## Environment reference (the load-bearing subset)

Every setting lives in `server/src/radd/config.py` (env prefix `RADD_`,
`.env` supported) — that file is the authoritative list. Highlights:

| Variable | Default | Purpose |
|---|---|---|
| `RADD_DATABASE_URL` | localhost dev DB | SQLAlchemy Postgres URL (required in prod) |
| `RADD_APP_BASE_URL` | `http://localhost:8000` | absolute links in emails/connectors |
| `RADD_SESSION_COOKIE_SECURE` | `false` | set `true` behind HTTPS |
| `RADD_RUN_WORKERS` | `true` | `false` = web-only process (worker split) |
| `RADD_WEB_DIST` | repo `web/dist` | built SPA to serve |
| `RADD_MODULES` | all | ordered module assembly (the plugin system) |
| `RADD_ATTACHMENT_STORAGE` / `RADD_S3_*` | filesystem | attachment backend |
| `RADD_SMTP_*` | disabled | outbound mail: digests, acks, comment replies |
| `RADD_EMAIL_INGEST_SECRET` | disabled | HMAC for `POST /integrations/email`. **Empty rejects everything** |
| `RADD_OIDC_*` | disabled | SSO (spec 40) |
| `RADD_LDAP_*` | disabled | AD directory login (spec 42) |
| `RADD_AI_*` | disabled | AI layer (spec 46) |
| `RADD_MCP_ENABLED` | `true` | MCP server at `POST /api/v1/mcp` (spec 45) |
| `RADD_GITLAB_*` / `RADD_FORGEJO_*` | disabled | VCS connectors |
| `RADD_GOOGLECHAT_*` / `RADD_ALERTMANAGER_*` / `RADD_MAIL_*` | disabled | notifier / alert / email intake (spec 47) |
| `RADD_WORK_WEEK_DAYS` | mon–fri | business-day SLAs + timesheet |

## MFA (TOTP)

Local-password accounts can enroll TOTP from their profile
(`POST /auth/totp/setup` → secret + `otpauth://` URI → confirm with a code).
Once enabled, `POST /auth/login` answers `401 {"detail":"totp_required"}`
and the client completes via `POST /auth/login/totp`. SSO/LDAP sign-ins are
untouched — the IdP owns MFA there. Recovery: an admin clears the user's
`user_totp` row (recovery codes are a listed follow-up).
