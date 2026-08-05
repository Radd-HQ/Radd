# <img src="web/public/brand/app-icon.svg" width="28" alt="" align="top" /> Radd

**Radd** (ردّ, Arabic for "reply") — self-hosted, AI-native work tracking + docs, and an answer to the paywall. AGPL, **never open-core**: SSO/LDAP + group sync, custom fields, automations, webhooks, and MCP are free forever — the features other tools gate behind a subscription.

- **Status & roadmap:** [PLAN.md §8](PLAN.md) · **Module map:** [docs/modules.md](docs/modules.md) · **Dev rules:** [CLAUDE.md](CLAUDE.md)

## Status

**Every pillar is built and runnable** (specs 01–48):

- **Tracking** — full RBAC incl. field-level grants, key-addressed issues (`/issues/TD-1234`), custom fields inline everywhere, workflow/labels/comments/teams, cycles, releases, saved views + the **SLQ** query language (autocomplete, swimlanes), automations, reporting, intake forms, time logging + timesheets, service desk (reporter/SLAs/canned responses), notifications + inbox, realtime (WebSocket), FTS + Cmd-K, attachments (filesystem or S3/MinIO), archive/delete, light theme, and the full React UI.
- **Sign-in** — local (argon2id) with **TOTP MFA**, **OIDC SSO** with group→role sync, **LDAP/AD direct bind** (no service account) with nested-group mapping.
- **Wiki** — doc spaces, page trees, version history + restore, issue↔doc links, search — the Confluence half.
- **Extensions** — an **Apache-2.0 SDK** (`sdk/`): drop-in Python plugins over the event stream (shotgunEvents ergonomics), plus an **embedded MCP server** so AI agents drive Radd through the same RBAC'd API as humans.
- **AI (optional)** — provider-agnostic (OpenAI-compatible/Anthropic): summarize, duplicate detection, natural-language → SLQ. Off by default; degrades gracefully.
- **Connectors** — GitLab, Forgejo/Gitea, Google Chat notifications, Alertmanager → issues, email → service-desk issues, signed webhooks out.
- **Deploy** — `Containerfile` + `compose.yaml` (two commands), Helm chart with an optional worker split, backup/restore docs: [docs/deploy.md](docs/deploy.md).

Depth follow-ups (real-time wiki co-editing, pgvector semantic search, recovery codes, …) are listed in [PLAN.md §8](PLAN.md).

## Quick start (dev)

```bash
podman compose up -d db
cd server
uv sync
uv run alembic upgrade head
uv run python -m radd.seed --email you@example.com --password change-me --name "You"
uv run uvicorn --factory radd.app:create_app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — the built web UI is served from the API server (log in with the
seeded credentials). API docs at `/docs`. `uv run pytest` runs the core-invariant suite against a
throwaway `radd_test` database — re-created and migrated to head on every run (override with
`RADD_TEST_DATABASE_URL`); the dev database is never touched. The
`server/scripts/demo*.sh` feature walkthroughs assume a **fresh** database (see [CLAUDE.md](CLAUDE.md)).

Import the Jira sample data — issues keep their **real Jira IDs 1:1** (internal-only files, see `server/scripts/sample_data/README.md`):

```bash
uv run python scripts/import_jira.py --file scripts/sample_data/jira_sample.json \
  --email you@example.com --password change-me
```

Frontend development (requires npm): `cd web && npm install && npm run dev` → http://localhost:5173
(proxies `/api` to :8000). `npm run build` refreshes the bundle served at :8000.
