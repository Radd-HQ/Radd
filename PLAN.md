# Project Plan — **Radd**

*Closed historical record — current state is the git tags + `docs/modules.md`, not this file. Kept as the original plan/build log (see the mid-file "historical snapshot" notes for section-level detail).*

A self-hosted, AI-native work tracking + docs platform. Issue tracker and wiki as equal citizens, built to replace Jira + Confluence at a VFX studio — and designed from day one to be an AGPL open-source product anyone can run without hitting a paywall.

*Supporting research in `research/` (landscape, architecture, auth).*

---

## 1. Mission & pledge

**Mission:** a modern, fast, clean tracker+wiki that is production-grade, self-hosted, radically extensible, and AI-native — where AI is optional, auditable, and provider-agnostic.

**The pledge (our market wedge):** everything competitors charge rent for is free forever in core:

- SSO (OIDC), LDAP/AD auth **and group sync** — (paywalled by OpenProject, Plane, Mattermost, GitLab EE, Grafana Enterprise)
- Typed, filterable **custom fields** — (Plane Pro, GitLab Premium, Leantime $39 plugin)
- Workflow transition rules & automations — (Plane Business)
- Audit log, API, webhooks, **MCP server** — (paywalled or absent everywhere)

Never open-core. Monetization, if ever, is hosting/support — never features.

## 2. Locked-in decisions (from interview)

| Decision | Choice |
|---|---|
| Audience/scale | Beyond one studio — multi-workspace, open-source product |
| License | AGPL-3.0 core + **Apache-2.0 extension SDK** (so studios can keep private connectors) |
| Backend | Python 3.12+ / FastAPI / SQLAlchemy 2 / Pydantic v2 |
| Frontend | React + TypeScript (Vite, TanStack, Milkdown) |
| Database | PostgreSQL 16+ — the **only** required dependency |
| Deploy | Docker Compose now; k8s-ready (stateless app, external state) |
| Realtime | WebSocket live updates (event-log-driven; sync-engine-upgradeable) |
| Wiki | Day one, equal citizen, real-time co-editing (Milkdown + Yjs) |
| Work model | Kanban + backlog, cycles/sprints, epics/hierarchy, roadmap/timeline, reporting + dynamic Gantt |
| AI | Optional extension; provider-agnostic (OpenAI-compatible + Anthropic native); per-user enable/disable |
| Identity | Native local + LDAP (AD) + OIDC (Google Workspace); OpenBao-friendly secrets |
| First integrations | GitLab, Forgejo, ftrack, chat notifications (Google Chat incl. air-gapped relay) |
| Jira migration | Later, as an importer extension — product first |
| Team | Solo + AI agents → modular monolith, ruthless phasing |
| Repo | Internal (studio GitLab) first, publish to GitHub at MVP |

## 3. What the research says (distilled)

- **From TD/DEV Jira analysis** (`research/jira-usage.md`): what's actually used is small — a handful of controlled-vocabulary select fields (Show, Department, Domain, Software, Site, Pipeline), labels heavily written by automation, time tracking (estimate + spent), a triage step, Code Review/Testing states, "relates" links, comments with images, and **one biweekly sprint spanning both projects**. Dead: story points, components (272 defined / 0 used in DEV), fixVersions (CI reimplemented releases as `release:stable:BNX.2.3` labels — we must make releases a first-class, automation-writable entity), and all Service Desk machinery.
- **From the landscape** (`research/landscape.md`): the free-auth + free-custom-fields + real-API combination doesn't exist in a maintained tool. Keep the deployable Forgejo-sized, not Huly-sized. "Agents as first-class users" is an empty niche in self-hosted.
- **From architecture research** (`research/architecture.md`): one **field-definition registry** should generate everything (API serialization, OpenAPI, UI forms, MCP tools, webhook payloads). Custom fields must serialize **inline on the entity everywhere** — Plane's side-channel API is the canonical failure. Event system: transactional outbox in Postgres, no broker. Plugins: out-of-process Python connector runner (shotgunEvents ergonomics), not in-process, not WASM.
- **From auth research** (`research/auth.md`): native local + LDAP bind + OIDC RP; identities keyed on `iss`+`sub` / `objectGUID`; GitHub-format hashed PATs; Grafana-style service accounts; two-level RBAC + per-issue confidential flag; no SAML/SCIM/policy-engine in v1.

## 4. Product design

### 4.1 Core concepts

```
Instance
└─ Workspace  (an org/studio; most installs have exactly one)
   ├─ Users, Groups, Service Accounts, Agents (AI principals)
   ├─ Teams           (named groups of users; assignable to projects and to work items alongside individual assignees)
   ├─ Cycles          (workspace-level iterations, opt-in per project — matches "PIPE - 116" spanning TD+DEV)
   ├─ Labels          (workspace or project scope; automation-writable)
   ├─ Projects        (long-lived containers, e.g. TD, DEV — key + numbered items: TD-123)
   │  ├─ Work Items   (typed; parent/child hierarchy: Epic → Issue → Sub-task)
   │  ├─ Item Types   (Bug, Feature, Help Request, Task, Proposal… each with a property set)
   │  ├─ States       (custom names within fixed categories: triage/backlog/todo/in_progress/done/canceled)
   │  ├─ Releases     (first-class, API/automation-driven — replaces the label hack)
   │  ├─ Views        (saved lenses: board / list / timeline; filter + group + display config)
   │  └─ Intake Forms (template-scoped fields for structured intake — the Proposal flow, artist support form)
   └─ Doc Spaces      (wiki: page trees, co-edited docs, templates; per-project or workspace-wide)
```

**Issue identity & URLs (added, spec 21):** an issue's identity is its **key** `PROJECT-NUMBER` (e.g. `TD-1234`), never a bare number. Numbering is per-project (so `TD-1` and `DEV-1` coexist — the Jira model). The key is the canonical address: issues are viewed at **`/issues/TD-1234`** (Jira's `browse/` model), resolved server-side by a real by-key lookup (`GET /items/by-key/{key}`). The old `/p/{project}/{number}` scheme (and the board's separate `/i/{number}` side-panel URL) are retired — every link (list, board, roadmap, views, parent/dependency links) points at `/issues/{key}`.
- **Project keys are globally unique** (instance-wide, not per-workspace) so `TD-1234` is an unambiguous address with no workspace context. **Trade-off:** this constrains the multi-tenancy vision (§Audience) — two workspaces can't both own a "TD" project. Accepted for the single-org studio case; revisit (workspace-prefixed keys?) if true multi-tenant hosting is pursued. Demo scripts therefore assume a fresh DB.
- **Imports preserve original IDs 1:1:** the Jira importer sets the item's number to the source number (`TD-48728` → `TD-48728`), so the native key *is* the Jira key — the old bookkeeping `jira_key` custom field is gone. `ItemCreate.number` (optional, `reserve_item_number` advances the project counter past it) is the general "create with an explicit key" path for any importer.

**Workspace visibility (added):** in a single-workspace deployment the workspace layer should be nearly invisible in the UI (the app already assumes the first/current workspace). The concept remains the multi-tenancy + cross-project-sharing boundary (users, teams, labels, fields, roles, cycles are workspace-scoped); it only surfaces prominently once an instance actually hosts more than one org.

Design rules borrowed deliberately from Linear, not Jira:
- **State categories are fixed**, names within them are custom. Analytics, rollover, and boards stay sane; Jira's status sprawl becomes impossible.
- **Views are saved lenses, never new data structures.** Boards, backlogs, roadmaps are all views over the same items. No board sprawl ("Copy of Global Domain Board - DO NOT USE").
- **Triage is a first-class inbox** per project (fixes TD's "New vs To Do" ambiguity; label `triaged` dies).
- **One hierarchy mechanism** (parent/child + type), max depth 3. No epic-link special case.
- **Cycles auto-roll** (biweekly PIPE sprints continue without a closing ceremony; unfinished items carry over).

### 4.2 Custom fields (the keystone feature)

- `field_definitions`: name, key, type, JSON-Schema validation, options, scope (workspace/project/type), flags: `required`, `indexed`, `ai_visible`, `source` (user | connector).
- Types v1: text, number, boolean, date, select, multi-select, user, url, duration. `connector`-sourced fields are read-only in UI and written by extensions (ftrack sync).
- Values live in one `custom_fields JSONB` column per entity; validated against the registry on write; lazily indexed (expression or GIN `jsonb_path_ops`) when flagged.
- **Registry generates everything**: REST serialization (inline on the entity), live `/openapi.json` component schemas, UI form/filter config, MCP tool schemas, webhook payloads, import/export mappings. A new field is instantly everywhere. This is the "any new endpoint/tool/field works automatically" requirement, structurally guaranteed.
- Seed config for the studio: Show(s), Department, Domain, Software, Site, Pipeline(Stable/Beta) — proving controlled-vocabulary selects on day one.

### 4.3 Work management v1

Board + list views (drag-drop, swimlanes, filters on any field incl. custom), backlog + triage inbox, cycles with capacity/carry-over, epics with rollup progress, relates/blocks/duplicates links, labels, priorities, time tracking (estimate + spent), comments (rich text, inline images, @mentions), attachments, watchers/subscriptions, notifications (in-app + email), full audit trail per item (the event log gives history for free), keyboard-first UX with command palette.

### 4.4 Docs (wiki)

Page trees in Doc Spaces; Milkdown editor (same component as issue descriptions/comments — one editor investment); real-time co-editing via Yjs with presence/cursors; page comments; mentions that link issues ↔ docs bidirectionally; templates; permissions inherit from space; versions/history via Yjs snapshots; full-text (and later semantic) search across issues + docs together. This is what makes it a credible Confluence exit.

### 4.5 Reporting & Gantt

- Dashboards with widgets fed by a query API: throughput, cumulative flow, burnup, cycle velocity, time-in-state (derived from the event log — no changelog archaeology like Jira).
- **Dynamic Gantt/timeline**: items with start/target dates + dependency links (blocks) render as an interactive timeline; epic bars roll up children; drag to reschedule writes back. Timeline is just another view type.

### 4.6 Automations (free, in core)

Rules: trigger (event filter) → conditions (any field, incl. custom) → actions (set field/state/assignee/label, move, notify, fire webhook, call connector action). Rate-limited per workspace, fully audit-logged. Covers the "Atlassian Automation User" patterns and the dated-priority-label hack properly.

## 5. Architecture

### 5.1 Shape: modular monolith + satellite processes

```
┌──────────────────────────────── app container ────────────────────────────────┐
│  FastAPI: REST /api/v1 · WebSocket /ws · MCP /mcp · Yjs doc sync /collab      │
│  Modules (strict boundaries, own routers/services/models):                    │
│   auth · workspace · fields(registry) · items · docs · views · cycles ·       │
│   releases · search · files · notify · automations · audit · events(outbox)   │
├────────────────────────────── worker container ───────────────────────────────┤
│  Event consumers (per-consumer offsets over the outbox):                      │
│   webhook dispatcher · notification sender · search indexer · automation      │
│   engine · scheduled jobs (group sync, digests, cleanup)                      │
└───────────────────────────────────────────────────────────────────────────────┘
        PostgreSQL 16+ (only required dep; +pgvector ext when AI enabled)
        Object storage: local disk default, S3-compatible optional

   satellite (optional, separate processes/hosts):
     connector runner(s) — Python SDK extensions (GitLab, Forgejo, ftrack, chat…)
     AI extension — triage/search/summarize workers + agent service accounts
     notification relay — for air-gapped zones
```

- Same codebase, two entrypoints (api / worker) — one container image. Stateless; scales horizontally; k8s-ready by construction (health probes, migrations as pre-deploy job, 12-factor config).
- **No Redis, no broker, no Elasticsearch in the base install.** Postgres does queues (outbox + `FOR UPDATE SKIP LOCKED`), pub/sub wakeups (LISTEN/NOTIFY), FTS, and vectors. Interfaces are seams: if a deployment ever outgrows this, swap implementations without touching modules.

### 5.2 Event stream (the spine)

- Every domain mutation appends to an `events` table **in the same transaction** (transactional outbox): monotonic `id`, entity ref, event type, actor, full payload (with custom fields inline), schema version.
- Retained and replayable. Consumers (in-process workers, connector runners, webhooks, AI workers) track their own offsets; LISTEN/NOTIFY provides low-latency wakeup, polling is the fallback.
- This one log powers: webhooks, realtime UI, notifications, automations, search/embedding indexing, connectors, audit/history, reporting (time-in-state), and — if we ever want Linear-style local-first sync — it is exactly the change log that requires. WebSocket-now, sync-engine-maybe-later is not a dead end.

### 5.3 API surface

- **REST `/api/v1`**: resource-oriented, cursor-paginated, filter query language shared with saved views. Custom fields inline on every entity. Idempotency keys on create. Client-generated UUIDs allowed (optimistic UI).
- **Live OpenAPI**: `/openapi.json` regenerated from the field registry — never drifts (Directus pattern).
- **Webhooks**: Standard Webhooks spec (HMAC-SHA256 over `id.timestamp.body`), Svix-style retries/backoff/dead-letter/auto-disable, per-endpoint secrets with rotation overlap, event-type filters.
- **MCP server** (embedded, Streamable HTTP at `/mcp`, PAT/service-account auth): curated stable tool list — `search_items`, `get_item`, `create_item`, `update_item`, `comment`, `get_schema`, `run_view`, `search_docs`, `get_doc`, `write_doc`, `list_projects` — whose JSON Schemas are generated per-session from the registry, so new custom fields appear to agents automatically. Free forever.
- **Agents as principals**: AI agents connect as scoped service accounts, are assignable, show distinctly in UI/audit, and act through the same tools humans' clients use. Per-user and per-workspace AI toggles gate all of it.

### 5.4 Realtime UI

WebSocket channel per client with subscriptions (project, view, item, doc). Server tails the event stream and pushes compact deltas; client keeps a normalized TanStack Query cache updated in place, plus optimistic writes with client UUIDs. Result: live boards, instant feel — ~90% of Linear's UX at ~10% of the sync-engine cost.

### 5.5 Docs collaboration

Yjs CRDT docs; server side uses **pycrdt** (+ pycrdt-websocket — the Jupyter-proven Python stack, keeps the backend single-language). Updates persisted to Postgres with periodic snapshot compaction; awareness (cursors/presence) over the same socket; Milkdown binding on the client. Issue descriptions use plain markdown (no CRDT) — only wiki docs pay the collab cost.

### 5.6 Search

FTS (Postgres `tsvector`, indexer as event consumer) across items, comments, docs — works with AI fully disabled. With the AI extension enabled: pgvector embeddings + hybrid retrieval (FTS + ANN fused with reciprocal rank fusion) powering semantic search, similar-issues, and dup detection.

### 5.7 Auth & authz (full detail in `research/auth.md`)

- Native trio: local (argon2id, break-glass admin) + LDAP/AD search-bind (LDAPS, nested groups) + OIDC RP with PKCE (Google Workspace, Keycloak, anything with discovery). JIT provisioning; identities table keyed on `iss`+`sub` / `objectGUID`; config-gated email linking.
- **Free group sync**: LDAP groups / OIDC claims → workspace+project roles; login-time refresh + hourly job; deactivate-never-delete with mass-disable guard.
- Tokens: GitHub-format PATs (`radd_pat_…` + checksum, SHA-256 stored, scopes, expiry, rotation, last-used); service accounts decoupled from humans, sync-exempt.
- AuthZ (revisedb): **roles are data, not enums.** A workspace carries role definitions (builtin admin/member/viewer seeded, custom roles creatable) each holding a set of `Permission` values; users get roles directly per project, via teams, or from workspace membership. Every action maps to a `Permission` checked against the actor's effective permission union in one tested `authz` seam. Admin UI exposes a role × permission matrix. Per-issue `confidential` flag still planned.
- **Field-level permissions (revisedb):** per-field read/write **grants to roles or teams** (no grants = default open to item readers/writers). Because the field registry is the single enforcement point (serialization, validation, OpenAPI, MCP all derive from it), restricted fields are filtered out of every representation for non-granted principals and writes are rejected centrally.
- **Comment visibility:** comments are `public` or `internal`; reading/writing internal notes is a permission (`comment.read_internal`) carried by roles — the artist-support pattern (artists see public replies, TDs keep internal triage notes).
- **Saved views:** boards/lists are saved lenses — named filter sets (states, kinds, assignees, teams, labels, priorities, custom-field values) + grouping, personal or shared per project/workspace.
- Sessions server-side in Postgres; TOTP MFA for local/LDAP; append-only audit log; rate limiting on auth paths; secrets via env/files (OpenBao agent-injection friendly).

### 5.8 Extensions layer

- **Primary surface: the Python connector SDK (Apache-2.0)** + runner, cloned from shotgunEvents ergonomics every pipeline TD already knows: drop a `.py` exposing `register(app)` into a connectors dir; the runner handles auth (service-account token), event subscription with offsets/replay, retries, hot reload, and per-connector process isolation. Full CPython — `requests`, ftrack API, studio site-packages all just work. Crash cannot touch the server.
- Extension capabilities: consume events; call the full REST API; own connector-sourced custom fields; register automation actions; register notification channels; register intake sources; importers/exporters. (UI extension points: later phase, deliberately.)
- **Wave-1 official connectors**: GitLab + Forgejo (branch/MR ↔ item linking, smart commit refs, MR state → transitions), Google Chat + generic chat notifications, ftrack field/status sync, Alertmanager intake. Jira + Confluence importers as extensions (M5).
- **Air-gapped notification relay**: connectors support standard proxy env vars, and for stricter zones a store-and-forward mode — the tracker enqueues notifications to a relay outbox; a small relay agent in the permitted zone **pulls** over the single allowed HTTPS channel (mutual auth) and delivers to Google Chat, pushing replies/acks back. No inbound connections to the air-gapped network; only the relay talks to the outside.

### 5.9 AI layer (an extension, not a core dependency)

- One provider config: OpenAI-compatible `base_url + model + key` (vLLM, Ollama, LiteLLM proxy, OpenAI) plus a native Anthropic path. Embeddings model configured separately.
- Features (each independently toggleable; workspace admin enables, users can opt out; nothing runs unless enabled): semantic search & similar-issues/dup detection; auto-triage suggestions (labels/priority/assignee/project from history — suggest-first, auto-apply rules optional); writing help (summarize threads, draft descriptions, release notes from completed items, cycle digests); agent access via MCP.
- All AI actions attributed to the agent principal in the audit log; AI never acts outside the same permission model as humans.

## 6. Tech stack summary

| Layer | Choice |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2 (asyncpg), Alembic, Pydantic v2, uv, ruff, pytest + testcontainers |
| DB | PostgreSQL 16+ (pgvector when AI on) — only required service |
| Frontend | React + TS, Vite, TanStack (Router/Query/Table/Virtual), dnd-kit, Milkdown (+Yjs), Radix + Tailwind, cmdk |
| Docs collab | Yjs ↔ pycrdt / pycrdt-websocket |
| Auth libs | Authlib (OIDC), bonsai or ldap3 (LDAP), pwdlib[argon2], pyotp |
| Files | Local disk default; S3-compatible optional |
| Observability | structlog JSON, Prometheus `/metrics`, OTel-ready, health/readiness endpoints |
| Packaging | One container image (api/worker entrypoints), docker compose; Helm chart at M5 |

## 7. Non-goals (deliberate)

SAML & SCIM (OIDC bridges cover it) · policy engine (the hand-rolled `authz` seam suffices) · Kafka/NATS/Redis/Elasticsearch · microservices · story points · per-issue-**type** permission schemes (Jira's worst complexity — per-field grants shipped instead) · components (labels + custom fields cover it) · service-desk SLA machinery · WASM plugin sandbox · public plugin marketplace · native mobile apps (responsive web only) · local-first offline sync engine (architecture keeps the door open). *(Per-**field** permissions were originally here but were built — see §8.)*

### 4.7 Teams & assignment (added)

Teams are first-class workspace entities (name, members). Work items carry both an individual `assignee` and an optional `team`; projects can have teams attached (which also grants project roles to team members); epics are work items, so team/individual assignment applies at every level of the hierarchy. Boards and lists filter by either.

## 8. Status & roadmap (updated)

Status and roadmap live in the tracker (the RADD project on project.radd-hq.com: epics per wave, the
release list, and the open issues) and in `BUILD-LOG.md` (what each wave built, newest first). §11 and
the per-spec addenda moved to `BUILD-LOG.md` on 2026-09-27 (RADD-1441).

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| ~~Scope: pillars still ahead, solo~~ RETIRED — every pillar (wiki, extensions+MCP, AI, connectors, packaging, MFA) has a shipped first implementation | The spec-and-fan-out waves did it; what's left is depth (§8 list), not pillars |
| Yjs/collab complexity in M3 | pycrdt is Jupyter-proven; fallback = single-editor + presence, CRDT stays on client contract |
| Postgres-only event bus ceiling | Fine to studio scale (a triple-digit weekly intake is trivial); consumer interface is the seam for NATS later |
| JSONB field query performance | `indexed` flag → expression indexes; category-constrained states keep hot queries relational |
| AGPL scaring studio contributions | Extension SDK is Apache-2.0; private connectors are unambiguously fine |
| Open-core temptation later | Public "never open-core" pledge in README from first public commit |
| Burnout/abandonment (the Taiga/Focalboard graveyard) | Dogfooding = the studio depends on it; publish once SSO + wiki land to attract co-maintainers |
| Global-unique project keys constrain multi-tenancy | Accepted for the single-org studio (gives unambiguous `TD-1234` keys, §8); revisit with workspace-prefixed keys if true multi-tenant hosting is pursued |

## 10. Naming

**Radd** — ردّ, Arabic for "reply / response." The name *is* the project's reply: to Atlassian and JetBrains, and to everyone who said a self-hosted, un-paywalled alternative was too much work or that there was no other option. Built out of defiance and to give back to open source — the "if you don't like it, build it yourself" answer, made real. Short and clean at the CLI (`radd`). Do a trademark / name-collision check before the public GitHub release; the code makes renaming cheap regardless (the product name lives in one place — the FastAPI title / SPA title — and the package is `radd`).
