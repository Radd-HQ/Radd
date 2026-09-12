# <img src="web/public/brand/app-icon.svg" width="28" alt="" align="top" /> Radd

**Radd** (ردّ, Arabic for "reply") is a self-hosted, AI-native issue tracker and
wiki — and an answer to the paywall. **AGPL, never open-core:** SSO/LDAP with
group sync, custom fields, automations, webhooks, SLAs, and the MCP server are
all here, free forever — the features other trackers gate behind a subscription
tier are the point, not the upsell.

> **Never open-core. Monetization, if ever, is hosting/support — never features.**

[![Latest release](https://img.shields.io/github/v/release/radd-hq/radd?label=release&color=5b6cf5)](https://github.com/radd-hq/radd/releases)
[![Checks](https://github.com/radd-hq/radd/actions/workflows/checks.yaml/badge.svg)](https://github.com/radd-hq/radd/actions/workflows/checks.yaml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/Radd-HQ)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-hjarrar-ffdd00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/hjarrar)

![The board view of the RADD project on the live instance, dark theme](docs/media/board-dark.png)

**We'd love your help.** Radd is built in the open and used
every day to track its own development. If you run a team, a studio, a lab or
a side project and want a tracker you actually own, try it, break it, and tell
us — or send the fix. [Contributing](#contributing) is a short read.

## Try it in five minutes

```bash
git clone https://github.com/radd-hq/radd.git && cd radd
podman compose up -d        # or docker compose — Postgres + app on :8000
podman compose exec app python -m radd.seed --email you@example.com --password change-me --name "You"
```

Open <http://localhost:8000>, sign in, and give it a fictional 26-issue project
to click around in:

```bash
podman compose exec app python scripts/import_jira.py \
  --file scripts/sample_data/jira_sample.json --email you@example.com --password change-me
```

That's the whole install: one container plus Postgres. A prebuilt image for
every release is at `ghcr.io/radd-hq/radd:<version>` (anonymous pulls, no
`latest` tag on purpose) — [docs/deploy.md](docs/deploy.md) covers TLS, backups,
S3 storage, upgrades and Kubernetes.

**Or just look at the real thing.** Radd develops itself in public at
<https://project.radd-hq.com>: the RADD project there is this repository's
actual tracker, bugs, timesheets and all. Every screenshot below was taken
from it at the current release — nothing staged, nothing invented.

## A tour

### Tracking work

Boards, lists and planning views are all *saved views*: a query in **SLQ**
(Radd's query language, with autocomplete) plus a display. Group by anything,
pin the ones you live in.

![A list view grouped by epic, with progress per epic](docs/media/list-dark.png)

### Ask instead of query

Type a sentence in the query bar and the answer lands as an SLQ query you can
read, edit and save — with a one-line explanation of what it matched.

![Ask mode: "open bugs, highest priority first" turned into `type = Bug AND category != done ORDER BY priority DESC`](docs/media/ask-dark.png)

### An issue, and what AI adds to it

Every issue has the same editor as the wiki (tables, code, diagrams, images),
a rail of fields that disables what you can't change instead of erroring
later, and a version-control tab fed by GitHub/Forgejo/GitLab. The AI actions
are optional and provider-agnostic; **Summarize** reads the whole issue —
description, comments and logged time — and answers beside it.

![An issue with its description, rail and the AI summary panel open](docs/media/ai-summary-dark.png)

<details>
<summary>The same issue in the light theme</summary>

![An issue in the light theme](docs/media/issue-light.png)
</details>

### Time, without the spreadsheet

Log time on an issue or on nothing at all; the timesheet rolls it up by issue
or by person, day, week or month, and flags outliers against your working
day. It has its own query dialect (`author = me AND issue.assignee != me`).

![The timesheet in week view, grouped by issue](docs/media/timesheet-dark.png)

### A wiki that knows about your issues

Spaces, page trees, version history and restore, page↔issue links, and the
same editor. The user and developer guides are written in it — and mirrored
to [this repo's wiki](https://github.com/radd-hq/radd/wiki) so you can read
them without an account.

![A wiki page in the light theme](docs/media/wiki-light.png)

### Dashboards, reports, and a home page that's yours

![A delivery dashboard: open items, items awaiting a version, throughput and cumulative flow](docs/media/dashboard-dark.png)

<details>
<summary>More: My Work, the command palette, planning and roadmap views</summary>

![My Work — requests, due soon, assigned to me](docs/media/my-work-dark.png)

![The command palette searching issues and wiki pages at once](docs/media/palette-dark.png)

![A planning view: the flat backlog with priority, assignee and state](docs/media/planning-dark.png)

![The roadmap view with its unscheduled panel](docs/media/roadmap-dark.png)
</details>

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
- **Integrations** — GitHub, Forgejo/Gitea and GitLab (commits/PRs/CI on the issue,
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

## Contributing

Yes, please — and not only code. The things that help most right now:

- **Use it and say what's wrong.** A bug report with the actual symptom is
  worth more than a guess at the fix. Open an issue here on GitHub; we file it
  on the live tracker and you'll see it move.
- **Small, sharp pull requests.** Fork, branch, `[RADD-###]` or a full
  description in the PR, and the same checks that gate `main` run on your fork
  (pytest, ruff, tsc, the browser smoke) with a read-only token — so a green
  run is yours to see before anyone reviews. A maintainer is auto-requested on
  every PR.
- **Plugins and connectors.** Radd is a kernel plus plugins, in-process
  (Python + a federated React remote) or out-of-process over the event stream
  (the Apache-2.0 SDK). If your team needs a connector we don't have, that's
  a great first project — `examples/acme-notes/` is the walkthrough.
- **Docs and the rough edges.** The [user and developer guides](https://github.com/radd-hq/radd/wiki)
  are written inside Radd's own wiki; a confusing page is a bug.

[docs/contributing.md](docs/contributing.md) has the setup, the conventions,
the pre-PR gates and the DCO note. [docs/modules.md](docs/modules.md) is the
map — every module, event type and cross-module edge — and
[CLAUDE.md](CLAUDE.md) is the working agreement the maintainer's agent
sessions follow, public because this project is also a demonstration of
AI-native development. Be kind: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development

```bash
podman compose -f compose.dev.yaml up        # dev db (:5456) + live-reloading API on :8000
                                             # (the container runs migrations itself)
podman compose -f compose.dev.yaml exec app \
  python -m radd.seed --email you@example.com --password change-me --name "You"
cd server && uv sync                         # host-side tooling
env RADD_DATABASE_URL=postgresql+psycopg://radd:radd@localhost:5456/radd \
  uv run pytest                              # ~2,500 tests, throwaway radd_test DB
cd ../web && npm install && npm run dev      # SPA on :5173, proxies /api to :8000
```

The dev stack's Postgres publishes on **5456** (the production-flavor compose
uses 5455), so host-run tools need `RADD_DATABASE_URL` pointed at it, as above.
`sh scripts/dev-clean.sh` brings up a second, empty instance beside your
working one — useful for anything about first-run behaviour.

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

## Community and support

- **Docs**: the [wiki](https://github.com/radd-hq/radd/wiki) — user guide,
  developer guide, release notes with a bill of materials per version.
- **The live instance**: <https://project.radd-hq.com> — the roadmap is the
  RADD project's backlog.
- **Releases**: [GitHub releases](https://github.com/radd-hq/radd/releases)
  with notes, SBOMs and vulnerability reports; images on ghcr.io.
- **Sponsoring** keeps the public instance running and the maintainer's time
  on what people ask for — never on unlocking features.
- **Security reports**: [SECURITY.md](SECURITY.md) — privately, please.

## License

The application is **[AGPL-3.0-only](LICENSE)**; the extension surfaces are
deliberately more permissive so building on Radd never forces your license:
both SDKs are **Apache-2.0**. Out-of-process extensions are entirely your
own. In-process plugins import the AGPL kernel, so distribute those under an
AGPL-compatible license — or keep them private; the AGPL's obligations attach
to distribution and network service, not to writing a plugin for your own
instance. Third-party attribution:
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
