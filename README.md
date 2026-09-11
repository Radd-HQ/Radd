# <img src="web/public/brand/app-icon.svg" width="28" alt="" align="top" /> Radd

**Radd** (ردّ, Arabic for "reply") is a self-hosted, AI-native issue tracker and
wiki — and an answer to the paywall. **AGPL, never open-core:** SSO/LDAP with
group sync, custom fields, automations, webhooks, SLAs, and the MCP server are
all here, free forever — the features other trackers gate behind a subscription
tier are the point, not the upsell.

> **Never open-core. Monetization, if ever, is hosting/support — never features.**

![The board view, dark theme](docs/media/board-dark.png)

## What's in the box

- **Tracking** — projects with key-addressed issues (`/issues/SKY-1004`),
  epics/subtasks plus a separate type axis, custom fields everywhere,
  configurable workflows with transition guards, labels, saved views
  (board/list/planning/roadmap/queue) with a real query language (**SLQ**, with
  autocomplete and NL→query), cycles, releases that sweep finished work,
  dependencies, bulk edit, intake forms, time logging + timesheets, dashboards
  and reports.
- **Service desk** — requesters by email (full loop: mail in, replies out,
  public tokened forms), SLAs with business hours and priority policies,
  canned responses with variables, CSAT, KB deflection.
- **Wiki** — spaces, page trees, version history + restore, issue↔page links,
  the same editor as issues (our own chrome over Milkdown/ProseMirror:
  tables, code blocks, diagrams, resizable images, AI actions).
- **Sign-in** — local (argon2id) with TOTP MFA, a Google/OIDC **provider
  registry** with per-domain provisioning rules, LDAP/AD direct bind with
  nested groups; service accounts with scoped API keys.
- **Access control** — full-CRUD RBAC with roles grantable per project or
  globally, field-level read/write grants, per-team internal comments,
  UI that disables what you cannot do instead of erroring after.
- **AI, optional and provider-agnostic** — OpenAI-compatible, Anthropic, or
  fully local (built-in CPU embeddings; point chat at any vLLM/Ollama):
  semantic + full-text search fusion, duplicate detection, summarize,
  natural-language queries, editor actions with reviewable diffs, AI storage
  and mail routing. Off by default; every feature degrades gracefully.
- **Agents are first-class** — an embedded **MCP server** exposes the whole
  tracking loop (file, transition, comment, log time, release, sweep) through
  the same RBAC as humans, with a catalog that adapts to what the caller may
  do.
- **Integrations** — Forgejo/Gitea and GitLab (commits/PRs/CI on the issue,
  releases that close the loop), Alertmanager, Google Chat, email in/out,
  signed webhooks, a REST API with OpenAPI docs, and a Python SDK for
  out-of-process extensions.
- **A real importer** — connect to Jira Server/DC, download once, map
  everything explicitly (fields, statuses, users, sprints — unused noise
  hidden and ignored by default), dry-run, import silently, roll back if you
  change your mind. IDs survive 1:1.
- **Operations** — one container + Postgres; encrypted scheduled backups with
  verification and a no-app restore path; Helm chart; monitoring page; SBOMs
  and vulnerability reports published per release.

![An issue, light theme](docs/media/issue-light.png)

## Run it

```bash
git clone https://github.com/radd-hq/radd.git && cd radd
podman compose up -d        # or docker compose — db + app on :8000
podman compose exec app python -m radd.seed --email you@example.com --password change-me --name "You"
```

Open <http://localhost:8000>, sign in, and (optionally) give it a fictional
26-issue project to click around in:

```bash
podman compose exec app python scripts/import_jira.py \
  --file scripts/sample_data/jira_sample.json --email you@example.com --password change-me
```

A prebuilt image for every release is on the project registry —
`git.radd-hq.com/radd/radd:<version>`, anonymous pulls, no `latest` tag —
see [docs/deploy.md](docs/deploy.md).

Before real people sign in, walk the **first-run hardening** list in
[docs/deploy.md](docs/deploy.md) — TLS, cookies, database password, and the
one default nobody guesses (the MCP endpoint is on). The same doc covers
upgrades, sizing, backups/restore, S3 storage, and Kubernetes.

**See it live:** Radd develops itself in public at
<https://project.radd-hq.com> — the RADD project there is this repository's
actual tracker, bugs and all.

## Development

```bash
podman compose -f compose.dev.yaml up        # dev db (:5456) + live-reloading API on :8000
                                             # (the container runs migrations itself)
podman compose -f compose.dev.yaml exec app \
  python -m radd.seed --email you@example.com --password change-me --name "You"
cd server && uv sync                         # host-side tooling
env RADD_DATABASE_URL=postgresql+psycopg://radd:radd@localhost:5456/radd \
  uv run pytest                              # ~2,300 tests, throwaway radd_test DB
cd ../web && npm install && npm run dev      # SPA on :5173, proxies /api to :8000
```

The dev stack's Postgres publishes on **5456** (the production-flavor compose
uses 5455), so host-run tools need `RADD_DATABASE_URL` pointed at it, as above.

[docs/contributing.md](docs/contributing.md) has the conventions, the
pre-PR gates, and the DCO note; [docs/modules.md](docs/modules.md) is the map
— every module, event type and cross-module edge; [CLAUDE.md](CLAUDE.md) is
the working agreement the maintainer's agent sessions follow (kept honest, and
public because this project is also a demonstration of AI-native development).

## Extending

Three tiers, sorted by distance from the process:

1. **MCP / REST** — anything that can speak HTTP automates Radd with a scoped
   PAT; the MCP catalog is the fastest way for an AI agent.
2. **The Python SDK** (`sdk/`, Apache-2.0) — out-of-process plugins and
   connectors over the event stream.
3. **In-process plugins** — backend modules on the kernel's contribution
   registries (entities, permissions, MCP tools, SLQ fields) and frontend
   remotes over module federation (`web/packages/plugin-sdk/`, Apache-2.0),
   hot-mounted at runtime. `examples/acme-notes/` is the walkthrough.

## License

The application is **[AGPL-3.0-only](LICENSE)**; the extension surfaces are
deliberately more permissive so building on Radd never forces your license:
both SDKs are **Apache-2.0**. Out-of-process extensions are entirely your
own. In-process plugins import the AGPL kernel, so distribute those under an
AGPL-compatible license — or keep them private; the AGPL's obligations attach
to distribution and network service, not to writing a plugin for your own
instance. Third-party attribution:
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

Security reports: [SECURITY.md](SECURITY.md) — privately, please.
