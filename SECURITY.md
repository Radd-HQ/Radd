# Security policy

## Reporting a vulnerability

**Do not open a public issue for a security problem.** The issue tracker at
project.radd-hq.com is public, and Radd instances self-host authentication,
directory credentials and webhook secrets — a vulnerability posted there is a
vulnerability published.

Report privately to **security@radd-hq.com**. Include what you can of: the
affected version (`/health` reports it), reproduction steps, and the impact you
believe it has. You will get an acknowledgement within **72 hours** and a
status update at least weekly until the report is resolved. If a report is
valid, we coordinate the fix and release before any public disclosure, and
credit you in the release notes unless you prefer otherwise.

## Supported versions

Radd is pre-1.0: fixes land on `main` and ship in the **latest tagged
release** only. There are no maintenance branches for older tags — upgrading
is the security update.

## Hardening a deployment

The first-run hardening checklist (TLS, secure cookies, trusted proxies, the
MCP endpoint's default, database credentials) lives in
[docs/deploy.md](docs/deploy.md). The short version: run Radd behind a
TLS-terminating reverse proxy, set `RADD_SESSION_COOKIE_SECURE=true` and
`RADD_TRUSTED_PROXIES`, change the compose stack's default database password
(`RADD_DB_PASSWORD`), and know that `POST /api/v1/mcp` — the AI-agent
endpoint — is **enabled by default** (`RADD_MCP_ENABLED=false` turns it off;
it enforces the same RBAC as the REST API either way).
