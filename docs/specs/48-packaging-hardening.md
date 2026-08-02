# Spec 48 — Packaging & hardening

The deployment pillar (PLAN §8): run Radd anywhere with two commands, split
the background work out of the web process when scale asks for it, and add
MFA for local-password accounts.

## App image + compose

- **`Containerfile`** (repo root, multi-stage): stage 1 `node:22-slim` builds
  `web/` (`npm ci && npm run build` — the container has npm even though the
  dev box doesn't); stage 2 `python:3.12-slim` + uv installs `server/`
  (locked sync, no dev deps), copies `web/dist`, non-root user, exposes 8000,
  `CMD uvicorn --factory radd.app:create_app --host 0.0.0.0 --port 8000`.
  `RADD_WEB_DIST=/app/web/dist` baked via env.
- **`compose.yaml`**: existing `db` service joined by an `app` service
  (build: Containerfile, depends_on db healthy, env `RADD_DATABASE_URL`,
  port 8000, named volume for `RADD_ATTACHMENTS_DIR`). Migrations run as the
  app container's entrypoint step (`alembic upgrade head` then uvicorn) —
  single-node convenience; Helm does it as a hook Job.

## Helm chart (`deploy/helm/radd/`)

Chart.yaml + values.yaml + templates: web Deployment (+ Service, optional
Ingress), optional **worker Deployment** (same image, `RADD_RUN_WORKERS`
split below), pre-upgrade migration Job, Secret-driven env (database URL,
SMTP, OIDC/LDAP, S3, AI…), PVC for filesystem attachments (or S3 via
values), liveness/readiness on `GET /api/v1/instance/login-options`
(unauthenticated). Values default to the all-in-one shape (workers in-web,
no separate deployment).

## Worker-process split

`RADD_RUN_WORKERS` (bool, default **true**): the five-plus background loops
(webhooks dispatcher, automations engine, notify consumer + emailer, search
indexer, SLA clock, googlechat consumer, mailintake poller) check it in
their `on_startup` hooks and stay dormant when false. The realtime
broadcaster and S3 bucket init always run (they serve the web tier).
Deployment story: all-in-one = one container, default. Split = web replicas
with `RADD_RUN_WORKERS=false` + exactly one worker replica with it true —
same image, same command, no new entrypoint. (Consumers are single-writer
by consumer-offset design; one worker replica, scale later via NATS per
PLAN §9.)

## MFA / TOTP (local-password accounts)

- `user_totp` table: user_id PK/FK, `secret` (base32), `confirmed_at`
  nullable, created_at. Pure `auth/totp.py`: RFC-6238 HMAC-SHA1 30s/6-digit
  code + verify with ±1 step drift + `otpauth://` provisioning URI —
  stdlib only, unit-tested against the RFC test vectors.
- Endpoints (session auth): `POST /auth/totp/setup` → `{secret, otpauth_uri}`
  (new random secret, unconfirmed, overwrites unconfirmed prior);
  `POST /auth/totp/confirm {code}` → enables; `DELETE /auth/totp {code}` →
  disables (code required — a hijacked session can't silently strip MFA).
  `GET /auth/totp` → `{enabled}`.
- Login flow: `POST /auth/login` with a TOTP-enabled account returns **401
  `{detail: "totp_required"}`** and NO cookie; the client then calls
  `POST /auth/login/totp {email, password, code}` (stateless — password
  re-verified with the code, uniform 401 on any failure) → cookie. SSO/LDAP
  logins are untouched — directory IdPs own their own MFA.
- Frontend (wave 2): login form shows a code field when it sees
  `totp_required`; profile page gains an "Two-factor authentication" panel
  (setup → QR-less secret + otpauth URI shown for the authenticator app,
  confirm code, disable).

## Backup/restore + env reference (`docs/deploy.md`)

Compose + Helm quickstarts; backup = `pg_dump` + the attachments dir (or
S3 bucket) + the env/secrets; restore order (db, attachments, start app —
migrations are idempotent); the full `RADD_*` env table generated from
`config.py`'s fields with one-line descriptions.

## Known simplifications

- No image registry/CI publishing (studio pushes to its own registry).
- Worker split is all-or-nothing (no per-consumer processes yet) and the
  worker tier still serves HTTP (harmless; no Service points at it).
- TOTP has no recovery codes yet (admin can clear a user's `user_totp` row
  via SQL/psql; recovery codes are a listed follow-up).
- Helm chart is deliberately minimal (no HPA/PDB/NetworkPolicy templates).
