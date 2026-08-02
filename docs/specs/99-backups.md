# Spec 99 — Backups

Scheduled and on-demand snapshots, encrypted at rest, restorable from the UI or
a shell. Self-contained: no other spec is a prerequisite.

## 1. Encrypt the artifact, not the columns

A backup contains everything — password hashes, TOTP seeds, API tokens, every
comment. The security property that matters is that **the file on disk is
useless without a key**, so encryption goes around the whole artifact.

That is deliberately *not* per-column encryption in the live database. That is a
separate, larger project (it makes the key load-bearing for login, needs
rotation tooling, and protects only the handful of columns that adopt it). One
AES-256-GCM stream over the artifact protects strictly more, for a fraction of
the work. Column encryption can come later without changing anything here.

**On by default.** The key is generated on first use into `backup_key_file`
(default `/data/radd-backup.key`, `chmod 600`) — a different volume from
`backup_dir`, so losing one doesn't lose both. Startup logs, loudly and once,
that the key must be backed up separately: without it every artifact is
unrecoverable. `RADD_BACKUP_ENCRYPTION=false` opts out for operators who rely on
filesystem encryption instead.

## 2. The artifact

```
radd-20260728-030000-a1b2c3d4.radd
┌──────────────────────────────────────────────┐
│ magic "RADDBK01" │ u32 len │ manifest (JSON) │  ← plaintext
├──────────────────────────────────────────────┤
│ AES-256-GCM chunks (1 MiB) of a tar:         │  ← encrypted
│   database.dump   (pg_dump -Fc)              │
│   attachments/…   (when included)            │
└──────────────────────────────────────────────┘
```

The manifest is plaintext on purpose: listing, sizes, dates and the
compatibility check must work without the key, and it holds nothing secret.

```jsonc
{"format_version": 1, "created_at": "…", "kind": "scheduled",
 "radd_version": "0.1.0", "schema_version": 1, "alembic_revision": "a1b2c3d4",
 "pg_server_version": "16.4", "encryption": "aes-256-gcm", "key_id": "3f9c1a2b",
 "chunk_bytes": 1048576, "base_nonce": "…", "includes_attachments": true,
 "payload_bytes": 481233920, "payload_sha256": "…", "created_by": "…"}
```

Each chunk's nonce is `base_nonce(8) ‖ counter(4)`; its AAD binds the manifest
hash, the chunk index and a final-chunk flag, so chunks cannot be reordered,
dropped, or spliced between artifacts. `payload_sha256` covers the plaintext
tar, verified on restore.

`schema_version` is a hand-incremented int (`radd/schema_version.py`, with a
changelog dict) bumped only when older data can no longer be made correct by
`alembic upgrade head` alone. Restore refuses a newer one outright and a
breaking-older one unless overridden. That is the whole mechanism — 20 lines,
not a subsystem.

## 3. Layout

Core, not a plugin: the CLI must restore an empty database, where no plugin
registry can load.

| Where | What |
|---|---|
| `radd/backup/` (`__main__.py` = CLI) | crypto, artifact, pg_dump/pg_restore, store, service |
| `radd/maintenance.py` | 503 flag + middleware, beside `CommitBeforeSendMiddleware` |
| `radd/schedule.py` | next-occurrence math, promoted from `automations/schedule.py` (rule 1 forbids importing it); `automations` switches over |
| `modules/backup/` | `backup_schedules` + `backup_runs`, router, events, settings page |

`pg_dump` is a **runtime requirement**, checked by a startup pre-flight that
refuses to boot when it is missing or older than the server (it must be ≥ the
server it dumps). `RADD_BACKUP_TOOLS_OPTIONAL=true` downgrades that to a
warning for a host-run dev server without a Postgres client. The image is
**Debian trixie**, which carries `postgresql-client-17` in its DEFAULT repos —
bookworm ships 15, too old for a PG 16 server, and would need the PGDG apt repo
plus a key and a purge step. Development runs IN the container
(`compose.dev.yaml`) with the repo bind-mounted, so the tools are simply there.

The inventory is the **directory**, not a table: a restore rewrites the
database, so a `backups` table would roll its own inventory back and erase the
record of the safety backup taken seconds earlier. `GET /backups` reads each
file's plaintext header.

## 4. Restore

1. Gate on `schema_version` and `key_id` — refuse early, with the reason.
2. Take a `pre_restore` safety backup. Non-negotiable.
3. Maintenance mode: 503 everywhere but the status endpoint, loops stopped.
4. Terminate other backends, dispose the pool.
5. `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` then `pg_restore
   --no-owner --no-acl --single-transaction`. Dropping ourselves rather than
   `--clean` is deterministic — `--clean` only drops what the dump contains, so
   tables from later migrations would survive into a "restored" database.
6. `alembic upgrade head`.
7. Extract attachments **over** the existing tree — orphaned files are harmless,
   deleting a user's file is not.
8. Recreate the engine, lift maintenance, emit `backup.restored`.

If step 5 fails, the safety backup is restored automatically; if that also
fails, maintenance mode stays on. A half-restored Radd must not serve traffic.
Restore is single-node — scale replicas to 1 first.

## 5. Surface

Instance admin only, every endpoint. Download is full data exfiltration and
upload hands `pg_restore` a file that executes SQL; there is no weaker tier
worth delegating.

```
GET/POST   /backups                 list (from disk) · take one now
GET        /backups/status          dir + writability, free space, tool versions, key id
GET        /backups/runs/{id}       progress
GET/DELETE /backups/{name}[/download]
POST       /backups/upload          streamed to disk, then verified
POST       /backups/{name}/restore
CRUD       /backups/schedules
```

`{name}` matches `^radd-\d{8}-\d{6}-[0-9a-f]{8}\.radd$` and resolves inside
`backup_dir` — a filename, never a path. DB credentials reach the subprocess as
libpq env vars, never argv (`ps` is world-readable). Every action emits an event,
which puts it in the audit trail for free.

**A default daily schedule is seeded on first boot** (03:00, keep 7, attachments
included). A backup system that must be configured protects the installs that
needed it least. Each finished artifact is verified immediately — `pg_restore
--list` over the decrypted dump plus the payload checksum — so "verified" is a
column, not a hope.

Settings → Backups: a status card (directory, free space, tool versions, key
id, next run), the schedules table, and the artifact table with Download ·
Restore · Delete, `Back up now` and `Upload`. Restore sits behind a typed
confirmation naming what will be replaced.

## 6. Config

`RADD_`-prefixed: `backup_dir` (`/opt/radd/backups`), `backup_key_file`
(`/data/radd-backup.key`), `backup_encryption` (`true`), `backup_scheduler_interval`
(`60`), `backup_pg_dump_path`/`backup_pg_restore_path`, `backup_tools_optional`
(`false`), `backup_compression` (`gzip:6`), `backup_retention_keep_last` (`7`),
`backup_min_free_bytes` (1 GiB), `backup_timeout_seconds` (`3600`),
`backup_max_upload_bytes` (`0` = unlimited).

The image creates `/opt/radd/backups` owned by a **fixed uid 10001**, `chmod
700`. A named volume inherits that and works; a bind mount does not, so
`docs/deploy.md` documents `chown 10001:10001 ./backups` and Helm sets
`fsGroup: 10001`.

## 7. Tests

- Crypto round trip, and every tamper: flipped byte, reordered chunk, truncated
  payload, wrong key, spliced chunk from another artifact — all must fail closed.
- Retention: honours `keep_last`/`keep_days`, never prunes manual/uploaded/
  `pre_restore`, never removes the last good artifact.
- Name validation: traversal, absolute paths, wrong shape.
- Manifest rejection: bad checksum, newer `schema_version`, unknown `key_id`.
- One end-to-end dump → drop → restore against the test database (`skipif` no
  `pg_dump`), asserting seeded rows survive.

## 8. Known simplifications

- Full dumps only; no incremental. WAL archiving is the cluster-layer answer.
- No off-site copy — the artifact lands in `backup_dir`. `docs/deploy.md` says
  that directory must not be on the database's disk.
- Restore is single-node and cannot downgrade a schema.
- s3 attachment storage is out of scope for artifact contents (the bucket has
  its own lifecycle).

## As-built notes

Shipped as specified. Deltas worth recording:

- **`--compress=zlib:6` is not a thing.** PG 16 names the codecs `gzip`, `lz4`,
  `zstd`; the default is now `gzip:6`. Caught by the first real dump, not by any
  amount of reading.
- **Terminating backends kills OUR OWN pooled connections.**
  `pg_terminate_backend` spares only the backend issuing it, so the next
  statement checked out a connection the server had already killed and the
  restore died on `DROP SCHEMA` with `AdminShutdown`. The pool is now disposed
  immediately after terminating, and again after the restore (cached plans and
  type OIDs are stale against a schema that no longer exists). Found by running
  a real restore; a unit test would not have.
- **A restore reverts the run table**, since run history lives in the database.
  The restore run's own row disappears (it was created after the dump was taken)
  and any run in flight AT DUMP TIME comes back marked `running`. So the restore
  path calls `mark_interrupted()` on completion, and the honest completion signal
  for a client is `maintenance: false` on `/backups/status` — not the run row,
  which 404s. This is the same reasoning that keeps the ARTIFACT inventory on
  disk; run history is simply the case where reverting is acceptable.
- **An uploaded artifact keeps its original `kind`.** The manifest is immutable
  by construction (its digest is the AAD for every chunk), so a re-uploaded
  scheduled backup still says `scheduled`. Retention is unaffected — it only
  prunes artifacts whose `schedule_id` matches the schedule doing the pruning.
- **Event types are `trigger=False`.** Registering them put seven admin events in
  the automation trigger dropdown and failed `test_trigger_registry.py`, which
  exists precisely to make that choice deliberate. They stay in the audit trail
  and on the webhook stream.
- **`size_bytes` is `BigInteger`** — an artifact can exceed 2 GB.
- **Autogenerate proposed unrelated drops** (`acme_notes`, the hand-built
  `doc_pages` FTS index); both were removed from the migration by hand.

Verified end to end against a throwaway database, with `pg_dump` shimmed to the
compose Postgres container (this dev box has no client installed):

- CLI: `status`, `create`, `list`, `verify`, `restore` — a deleted user came
  back, a row added after the backup was gone, the attachment was restored.
- Artifact secrecy: `demo@example.com`, attachment contents, `argon2` and even
  table names are absent from the file; the manifest header still reads without
  a key. A different key is refused by id before any I/O.
- API: status, schedules CRUD, create + run polling, download, upload (valid and
  junk), delete, and a maintenance-mode restore — `/projects` returned 503 while
  `/backups/status` stayed 200, and maintenance released on completion.
- Path handling: every name reaching the endpoint is rejected 404; the `..`
  probes never served anything outside the directory (Starlette normalises them,
  so they fall through to the SPA).
- Rendered proof: headless CDP screenshot of Settings → Backups — status facts
  populated, both tables present, no console errors, no horizontal overflow.

Tests: `test_backup_artifact.py` (29 — round trip at chunk boundaries, wrong key,
flipped byte, truncation, manifest tampering, cross-artifact splice, missing
footer, name validation, key file permissions) and `test_backup_retention.py`
(14 — retention policy, changelog completeness, compatibility gates). Suite: 1034.

## Follow-up — trixie image + dev-in-container

The PGDG dance in §3 is gone. Two changes, both simplifications:

- **The image is `python:3.12-slim-trixie`.** Debian 13 carries
  `postgresql-client-17` in its default repos, so installing the client is one
  `apt-get` line — no third-party repo, no signing key, no `curl`/`gnupg` to
  purge afterwards. Client 17 dumps the PG 16 server fine (the rule is client
  **≥** server).
- **`compose.dev.yaml` runs the API in the container with `./server` mounted.**
  This is what makes `pg_dump` a reasonable hard requirement: developers get the
  tools without installing a Postgres client, so `RADD_BACKUP_TOOLS_OPTIONAL`
  stops being the normal path and goes back to being an escape hatch.

Three things that had to be right for the mount to work:

- **The venv moved to `/opt/venv`** (`UV_PROJECT_ENVIRONMENT`). Bind-mounting the
  repo over `/app/server` would otherwise shadow `.venv` and leave the container
  with no dependencies. uv installs the project editable, so the mounted source
  is genuinely what runs (`radd.__file__` -> `/app/server/src/radd`).
- **The Containerfile gained a `dev` target** that does not depend on the `web`
  stage, so a dev build never runs npm; `web/dist` is mounted instead.
- **`name: radd-dev`.** Without an explicit project name, compose derives one
  from the directory and the dev stack's containers collide with
  `compose.yaml`'s — starting it REPLACED the running `tracker_db_1`. Found by
  doing it.

**Pre-existing breakage found while verifying:** the production image had been
unbuildable since spec 94. `npm ci` resolves `@radd/plugin-sdk` from the
workspace tree, but the web stage copied only the root `package.json`, and
`package-lock.json` had no workspace entry at all (npm is not installed on this
dev box, so the lockfile was never regenerated when the SDK package landed).
Fixed by copying `web/packages` before `npm ci` and regenerating the lockfile in
a node container — a two-entry change, no dependency churn.

Verified: both targets build; the production image runs as uid 10001 on Debian
13.6 with `pg_dump` 17.10 and the SPA baked in; the dev stack takes a real
encrypted backup (PG 17 client, PG 16 server) that lands on the host bind mount
owned by the host user, and a host-side source edit live-reloaded into the
running container. Suite: 1034.

**Dev-container gotcha.** Moving development into the container
broke corporate directory access, and the symptom did not name the cause: LDAP
returned `invalid server address` in the container while enumerating 1027 users
host-run. Podman's internal resolver forwards to the host's `/etc/resolv.conf`,
which under systemd-resolved is the `127.0.0.53` stub — unreachable from the
container's network namespace. ROUTING was fine (a raw TCP connect to the AD
server's IP from inside the container succeeded); only resolution failed.
`compose.dev.yaml` now takes `dns: ${RADD_DEV_DNS:-}` — empty is ignored, so the
portable default is unchanged, and a gitignored root `.env` supplies real
resolvers where a split-DNS zone matters. Podman keeps its own DNS for service
discovery alongside, so `db` still resolves.
