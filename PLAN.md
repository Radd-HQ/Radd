# Project Plan — **Radd**

A self-hosted, AI-native work tracking + docs platform. Issue tracker and wiki as equal citizens, built to replace Jira + Confluence at a VFX studio — and designed from day one to be an AGPL open-source product anyone can run without hitting a paywall.

*Plan date:. Supporting research in `research/` (jira-usage, landscape, architecture, auth).*

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

The original M0–M5 milestone plan was overtaken by fast iteration: the **tracker is built well past the "prototype,"** while several later pillars (SSO, wiki, extensions, AI) are still untouched. This section is the authoritative status; `docs/modules.md` is the per-module detail and the "Known simplifications" list.

### ✅ Built and live (front-to-back, verified; served at `http://localhost:8000`)

**Platform & foundation**
- Modular monolith — FastAPI / SQLAlchemy 2 / PostgreSQL 16; plugin module system (`RaddModule` assembled from `RADD_MODULES`); transactional **event outbox** with per-consumer offsets + in-transaction hooks; **live OpenAPI** generated from the field registry; the built React SPA is served from the API; commit-before-response middleware.

**Auth & access control**
- Local auth (argon2id), server-side sessions, personal access tokens, service accounts.
- **Roles-as-data**: builtin admin/member/viewer + custom roles with permission sets; **full action RBAC** enforced on every endpoint through one `authz` seam; direct project membership + team-granted project roles.
- **Field-level read/write permissions** granted to roles *or* teams *(originally a non-goal — now built)*; public/internal **comment visibility** gated by permission.
- **Issue types (spec 51)**: a first-class per-project **Type** axis (Bug/Task/Story/Feature/Epic, configurable, colored chips) — the classification the tracker was missing, kept orthogonal to the epic/issue/subtask hierarchy. `itemtypes` module + `type_id` on items + SLQ `type` filter; rendered as OtherTracker-style chips on boards/lists/the issue rail; managed under project settings. Plus a **OtherTracker-style settings pass**: value-chips for Type/Priority/State, dismissible info banners on the config editors, and up/down reordering.
- **Settings scope + RBAC CRUD (spec 50)**: full-CRUD permission model (77 atoms, `create/update/delete` on every resource incl. the missing `item/comment/worklog/doc.delete`; `*.manage` umbrellas expand transitively — backward-compatible); settings split into **instance / workspace / project** surfaces with **scope-gated nav** and per-project settings nested under `/p/$key/settings/*`; a **scalar-settings cascade** (`scoped_settings` — project → workspace → instance → env, first key `work_week_days`); **builtin-field READ grants** (blanked out of item representations); **per-team internal comments** (teams narrow the `comment.read_internal` audience, enforced on list/notify/history/MCP).

**Work tracking**
- Workspaces; projects with **globally-unique keys**; **key-addressed issues** at `/issues/TD-1234` (Jira `browse/` model).
- Work items: epic/issue/subtask hierarchy, per-project numbering, **custom fields inline everywhere** via the registry, workflow states (fixed categories + custom names), labels, priorities, assignee + team, comments (public/internal), dependency links (blocks/relates/duplicates), start/target dates.
- **Cycles/sprints** (workspace-level, span projects; **draft/staging cycles** with optional dates — a dateless cycle is a planning bucket, never active), **releases** (project-scoped, automation-writable).
- **Saved views** (custom boards/lists) driven by **SLQ** — a JQL-like query language with server-driven **autocomplete** — plus **swimlane boards** on any field axis, and a **Cycle** grouping axis (every cycle a collapsible section with a status/dates/progress summary, an optional name-glob filter, and a Backlog bucket for un-cycled work).
- **Automations** (event → SLQ-condition → action rules engine), **reporting** (throughput, cumulative flow, burnup, velocity, time-in-state), **intake forms**.
- **Time logging + timesheets** (spec 22, per-project-optional): item estimate + worklogs (Jira-style durations, configurable work categories, notes), estimate/logged/remaining, and a workspace **timesheet** (day/week/month, filter by team or person, drill into a day/employee/issue).
- **Webhooks** (Standard Webhooks: signed, retried, dead-lettered).
- **Jira importer** — preserves original issue IDs 1:1 (`TD-48728` → `TD-48728`).
- **Notifications + watchers + Inbox** (spec 26): assignment/@mention/state-change/comment fan-out from the outbox, auto-watch, `/inbox` + sidebar badge, SMTP email digests.
- **Realtime** (spec 27): WebSocket tail of the outbox → entity-level cache invalidation; boards/issues/inbox live-update.
- **Search + Cmd-K palette** (spec 28): Postgres FTS (key/title/description/public comments) + quick-open/navigation palette.
- **Attachments + markdown editor** (spec 29): filesystem-backed uploads, paste-to-attach, safe markdown rendering, `@[Name](uuid)` mention autocomplete. WYSIWYG editing is Milkdown/Crepe (spec 54, §11).
- **Service desk** (spec 30): reporter/requester field (SLQ `reporter`), SLA policies + pause-aware timers + exactly-once breach events → notifications, canned responses.
- **GitLab connector** (spec 31): webhook receiver auto-linking branches/commits/MRs via the vcs seam + optional merge transitions.
- **"My Work" home + polish** (spec 32): personal landing dashboard (assigned/due-soon/starred/inbox/recently-viewed), saved-view CSV export, `/` palette hotkey.
- **S3/MinIO attachment storage** (spec 33): storage seam — filesystem default or any S3-compatible store with presigned-URL downloads.
- **Personal profile** (spec 34): avatar (color/emoji, shown across the UI), timezone, PATCH /auth/me, tokens panel on the profile page.
- **Work week + business-day SLAs** (spec 35): RADD_WORK_WEEK_DAYS at GET /instance, SLA `work_week_only`, timesheet weekend dimming.
- **RBAC extensions** (spec 36): per-entity manage permissions with umbrella implication, wider member floors (cycles/timesheets/forms), builtin-field WRITE rules (Builtin fields section of /settings/fields).
- **Polish** (spec 37) + **item archive/hard delete** (spec 38) + **light theme & density** (spec 39) + **list "Load more" pagination** (spec 41).
- **SSO — OIDC** (spec 40): code+PKCE relying party, JWKS-verified id_tokens, SSO-only user provisioning, group→role sync each login, login-page button.
- **LDAP/AD bind** (spec 42): **direct UPN bind** (`ldap3`, no stored service account — the pipe-status pattern), nested-group admin mapping via AD's transitive matching rule, same SSO-only provisioning + per-login role sync as OIDC (shared `sync_workspace_membership` seam), Email/Directory toggle on the login page. `RADD_LDAP_*` env; dormant when unset.

**The remaining pillars — ALL landed (specs 43–48):**
- **Wiki** (spec 43): doc spaces + page trees + versions + optimistic-concurrency editing (markdown, the existing safe editor), issue↔doc links both ways, FTS + Cmd-K "Docs" results, doc.read/write/manage RBAC, full two-pane frontend with history/restore. (Yjs/pycrdt co-editing deferred behind the same PATCH seam — §9 fallback shipped.)
- **Extensions SDK** (spec 44): `sdk/` — an independent **Apache-2.0** `radd-sdk` package: PAT-authed client, shotgunEvents-style plugin runner over `GET /events` (crash isolation, hot reload, offset checkpoint, at-least-once), `radd-runner` CLI, example plugin.
- **MCP server** (spec 45): embedded at `POST /api/v1/mcp` — hand-rolled Streamable-HTTP JSON-RPC, PAT principals through the ordinary RBAC seams, tool schemas (incl. custom fields) generated live from the field registry. **Agents-as-principals is real.**
- **AI layer** (spec 46): optional + provider-agnostic (OpenAI-compatible/Anthropic): item summarize, similar/dup detection (FTS always, LLM rerank when enabled), NL→SLQ with server-side compile validation. Issue-page AI panel + "Ask" on the SLQ bar.
- **Connectors** (spec 47): Forgejo/Gitea (HMAC webhook → vcs links + merge transition), Google Chat notifier (outbox consumer, head-start bootstrap), Alertmanager intake (fingerprint-dedup → items/comments), email-to-issue (IMAP poller → service-desk items/reply comments).
- **Packaging & hardening** (spec 48): app `Containerfile` (verified boot) + compose app service + **Helm chart** (worker-split deployments, migration Job, probes), `docs/deploy.md` (backup/restore + env reference), `RADD_RUN_WORKERS` worker split, **MFA/TOTP** (RFC-vector-tested, challenge login, profile enrollment).

**Frontend (React SPA)**
- Login, app shell, projects index; boards (drag-drop), lists (with an ad-hoc SLQ bar), the dedicated full-page issue view, roadmap/Gantt, reporting dashboards.
- Full admin/settings suite: fields (+ permission-grant editor), states, labels, teams, workspace members, per-project access, roles matrix, tokens, cycles, releases, automations rule builder, intake-form builder + submit page.
- SLQ query editor with autocomplete, view/board builder, permission-gated affordances.

### 🔲 What remains — the roadmap lives in the tracker (RADD-603)
Every pillar from the original vision has a shipped first implementation. The depth list that
used to sit here is now **filed as issues in the RADD project on project.radd-hq.com** — the
roadmap view there is the plan, and this document stops being a second source of truth that
drifts (two entries here had already shipped — pgvector in spec 103, storage GC in spec 102 —
while still listed as open):

- **RADD-676…687** — the depth items: wiki co-editing (Yjs/pycrdt), TOTP recovery codes,
  GitLab connector on the SDK runner, ftrack + air-gapped Chat relay, per-project connector
  config, j/k navigation, board WIP limits, issue templates, comment reactions, Confluence
  importer, per-user notification preferences, board/view pagination beyond 200.
- **RADD-688** (epic) — open-source release readiness: synthetic sample data (RADD-689),
  the security checklist pass (RADD-690), license/trademark clearance (RADD-691), the
  never-open-core pledge in the README (RADD-692).

(Running list of known simplifications stays in `docs/modules.md`.)

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| ~~Scope: pillars still ahead, solo~~ RETIRED — every pillar (wiki, extensions+MCP, AI, connectors, packaging, MFA) has a shipped first implementation | The spec-and-fan-out waves did it; what's left is depth (§8 list), not pillars |
| Yjs/collab complexity in M3 | pycrdt is Jupyter-proven; fallback = single-editor + presence, CRDT stays on client contract |
| Postgres-only event bus ceiling | Fine to studio scale (TD ≈ 122 issues/wk is trivial); consumer interface is the seam for NATS later |
| JSONB field query performance | `indexed` flag → expression indexes; category-constrained states keep hot queries relational |
| AGPL scaring studio contributions | Extension SDK is Apache-2.0; private connectors are unambiguously fine |
| Open-core temptation later | Public "never open-core" pledge in README from first public commit |
| Burnout/abandonment (the Taiga/Focalboard graveyard) | Dogfooding = the studio depends on it; publish once SSO + wiki land to attract co-maintainers |
| Global-unique project keys constrain multi-tenancy | Accepted for the single-org studio (gives unambiguous `TD-1234` keys, §8); revisit with workspace-prefixed keys if true multi-tenant hosting is pursued |

## 10. Naming

**Radd** — ردّ, Arabic for "reply / response." The name *is* the project's reply: to Atlassian and JetBrains, and to everyone who said a self-hosted, un-paywalled alternative was too much work or that there was no other option. Built out of defiance and to give back to open source — the "if you don't like it, build it yourself" answer, made real. Short and clean at the CLI (`radd`). Do a trademark / name-collision check before the public GitHub release; the code makes renaming cheap regardless (the product name lives in one place — the FastAPI title / SPA title — and the package is `radd`).

## 11. Immediate next steps

**All original pillars shipped through spec 48; three more landed** —
**spec 50** (settings scope + full-CRUD RBAC + scalar-settings cascade + builtin-field
read grants + per-team internal comments), **spec 51** (issue types — a per-project
classification axis, colored chips, orthogonal to the epic/issue/subtask hierarchy),
**spec 52** (issue `#`-mentions in every markdown editor + per-field render widgets).

**Current runtime state (end of the 18-round polish day; rounds 14–18 in
commit AFTER `6f103a9`):** alembic head `5e4a41d09ca0` (single head; late-day chain:
`7ec22a4a1c25` view quick_filters → `c536f26534fb` item_cycle_records [spec 56] →
`5e4a41d09ca0` view sharing [spec 57]); **625** core tests green; served on
`http://localhost:8000` (detached uvicorn, current code, log `server/var/server.log`).
Frontend `web/dist` built + served. Everything in the bullets above is LIVE
and verified (Playwright chromium via `uv run --with playwright` — browser cached in
~/.cache/ms-playwright; per-feature verification detail in the round entries below and
in memory). Spec docs for the late rounds: `docs/specs/55-57*.md`. **Open decisions /
follow-ups:** run `scripts/fix_jira_markup.py --apply` (dry-run showed 11 451 comments
+ 1 035 descriptions would canonicalize; display already correct via render-time
conversion); a members-page UI for the user-merge endpoint; run
`jira_fetch_attachments.py` against real Jira (needs a PAT) before the next re-import;
label-chip truncation on list rows (cosmetic); **teams have no DELETE endpoint** (found
during spec-57 QA — cleanup needed SQL); **ask the user whether "share a personal
space" meant WIKI spaces** (doc spaces have no ACLs; the `view_shares` pattern
generalizes); ops guidance: **complete cycles, don't delete them** — deleting
CASCADE-drops the item↔cycle stint history (PIPE-116/117's 294 carryover records were
lost this way, unrecoverable).

** round (LIVE, committed with the service-desk day): automations rework + UI polish.** **Spec 58**
(`docs/specs/58-automation-event-conditions.md`): rules trigger on ANY catalog event
type (52 across items/comments/worklogs/attachments/links/cycles/releases/docs/admin;
`trigger` = raw event-type string, data-migrated) + nestable all/any/none **event
conditions** (`actor`/`changed_field`/`old_value`/`new_value`/`state_category`/
`payload`-path subjects, 11 operators, pure evaluator `automations/conditions.py`,
12 unit tests) + `GET /automations/catalog` + recursive condition-builder UI, AND
**spec 58b universal actions** (create_item/send_webhook[HMAC]/post_chat/notify_user w/
`{{token}}` templates — run even on itemless triggers; new NotificationType.AUTOMATION).
PLUS **spec 59** (itemless/general worklogs: nullable item + project/workspace anchors,
category REQUIRED + first-class in the timesheet — per-category strip, By-category
grouping, Log-time modal; `docs/specs/59-general-worklogs.md`). PLUS **spec 60** (team-restricted cycle visibility [`cycle_teams`, admin-only bypass,
404-hidden] + collapsible sidebar sections + projects-fold-by-default w/ current-route
auto-expand; `docs/specs/60-cycle-visibility-sidebar.md`). Alembic head
`8325cd80bd6d`; **648** tests green; verified E2E (comment-visibility rule +
state-into-done rule, both positive & negative). Same-day polish, all live: settings
Fields-page merge (Field Rules tab folded in as Builtin-fields section w/ shared
GrantsEditor), brand icons (`web/public/brand/`, favicon/sidebar/login, RaddMark/
RaddTile components), cycle-handle stats (estimate/logged/remaining chips one-line
right-aligned, RED negative remaining — cycle aggregate now unclamped Σ(est−logged)),
list-row rework (labels capped +N mid-row, fixed-width square state pills far right),
**per-surface card display config** (`lib/card-display.ts` slots + labels cap + zoom
slider, DisplayMenu on saved views/list/board/planning, localStorage per view/project —
server-side persistence on the View model is the designed follow-up), selenium
screenshot harness in the bg-job tmp (system Firefox + geckodriver).

** SERVICE-DESK WAVE (LIVE, committed): specs 61–66.** Closed every gap
from the service-desk audit; specs in `docs/specs/61-…66-….md` (each has As-built
notes). **Spec 61 workflow transitions** — optional per-project transition graph +
validation guards (`workflow_transitions`, `TransitionCheck` require_assignee/
estimate/team/comment/fields; `SettingKey.WORKFLOW_TRANSITION_MODE` off/guards/
strict via the spec-50 cascade, default off; enforcement in items.update_item AFTER
the whole patch applies → 422 {errors[]}; `GET /items/{id}/allowed-transitions`
drives graying/tooltips; editor on the States settings page). **Spec 62 requester
loop** — reporter auto-watch (notify planner), `mail_contacts` (one external
requester per item), auto-ack w/ threading subject `[KEY]`, outbound consumer
`mailintake.outbound` (public agent comments → email to contact, cursor seeds at
HEAD, at-most-once), plus-address project routing (`support+td@`), public tokened
forms (`/public/forms/{token}` API + SPA route outside the auth guard), shared
`radd/smtp.py`. **Spec 63 SLA depth** — per-priority policies + ordered FIRST-MATCH
(semantic change: ONE policy per item; evaluate-all retired), business-hours
windows (`business_start/end_minute`), `POST /items/sla/batch` (chips on list/
board/views/planning via the card-display `sla` slot, default off), `GET
/reports/sla` weekly buckets + Service-desk report card (project + workspace
reports). **Spec 64 queue views** — `ViewType.QUEUE` + batched `POST /views/counts`;
sidebar "Queues" section w/ live count badges; queue page = list variant w/
reporter/age/SLA columns, breached-first urgency ordering, DnD-rank disabled.
**Spec 65 CSAT** — new `csat` module: survey on resolve (consumer `csat.sender`,
per-project opt-in `SettingKey.CSAT_ENABLED` default OFF, recipient = mail contact
else reporter email, once per item), public `/public/csat/{token}` API + SPA star
page, rating chip in the rail, csat_avg/csat_count in the SLA report. **Spec 66
polish** — canned-response `{{variables}}` + render endpoint, automation
`send_email` universal action (to = literal|reporter|assignee|contact), KB
deflection `GET /search/deflect` + DeflectionPanel under the title input
(new-issue modal + authed form page). **Ground truth:** migration chain
`8325cd80bd6d → 57614f09f956 → 7be36ff1ac2c → fb577d3807f9 → d90a8f7daa8a`
(single head, applied); **712 pytest green**; web/dist rebuilt; **:8000 restarted
on this code** (NOTE: currently running as a background-job child, not the usual
setsid detach — re-detach it the standard way whenever convenient). Smoke-verified
live: allowed-transitions/deflect/mail-contact/csat/public-404s. **Operational:**
SMTP is still unconfigured (`RADD_SMTP_HOST` empty) so ack/reply/CSAT/send_email
paths are armed but dormant — outbound + csat cursors seed at stream HEAD, so
setting SMTP later never replays history; CSAT + transition enforcement are
per-project opt-ins (both default off); first-match is a real semantic change if
old complementary SLA policy pairs existed (fold targets into one policy).
Follow-ups seeded in the specs' Known simplifications (per-queue columns,
business-time report averages, custom-field canned tokens, deflection on the
public form). **Same-day addendum:** forms gained a proper ITEM-description
area (user caught that submit pages only had the summary): `forms.description_enabled/
description_prompt/description_required` (migration `40573860b0bd`, area ON by
default for new AND existing forms), textarea on the authed + public submit
pages, required enforced server-side (`description: required` 422), builder
controls (toggle/prompt/required) — **715 tests**, head `40573860b0bd`.
**Addendum 2 — workspace board views got state drag** (user: "board views can't
transition issues, only the project board can"): spec 24 had disabled state DnD
on workspace-spanning views (name-keyed buckets, "ambiguous"). Now `GET /states`
accepts `workspace_id` (readable projects' states), `bucketMovePlan` resolves a
name-keyed drop in the DRAGGED ITEM'S own project, `dragEnabledForAxis` lost its
projectScoped gate, and an unresolvable drop (item's project lacks that state
name) toasts instead of silently snapping back. Covers board columns AND state
swimlanes; spec-61 transition guards apply to these drags like any PATCH.
**Addendum 3 — project default surfaces** (user: "why can't I modify the default
board/list for a project?"): the built-in /p/KEY/board|list were zero-config
spec-04 surfaces. Now `views.project_default` (board|list; migration
`97f19379ae3c`) designates a saved view as the project's default — the builtin
routes redirect to it. `PUT/DELETE /views/{id}/project-default`
(project.manage): view must be project-scoped + slot-compatible (board→board,
list→list|queue) + workspace-visible, one per slot (previous holder cleared),
and PATCH/sharing changes that would break a live designation 409. Picker on
project settings → General ("Default surfaces"). **716 tests**, head
`97f19379ae3c`, :8000 restarted.
**Addendum 4 — cycle handles unified** (user: "why are the planning-view cycle
cards different from the project planning page?"): two renderers had diverged —
cycle-axis view sections got the handle (status pill, dates badge,
estimate/logged/remaining chips, done pill, progress bar) while
`routes/planning.tsx` still drew its round-11 hand-rolled header.
`CycleHeaderStats` moved into `components/cycles/CycleBadges.tsx` (the shared
atoms file) and the standalone planning page now composes the SAME handle —
done pill + progress come from `GET /cycles/{id}/stats` (server-real, not the
loaded page subset). Frontend-only; dist rebuilt.
**Addendum 5 — planning page rebased onto the view engine** (user showed the
two surfaces still structurally differing and asked for builtins to share the
views' base): `routes/planning.tsx` REWRITTEN as a thin wrapper over the exact
components planning views use — one paged `infiniteItemsQuery` fetch,
`groupItemsForView` cycle axis, `ViewList` (collapsible sections, ListRow
rows), `bucketMovePlan` DnD, shared Load-more. Deliberate config deltas only:
completed cycles hidden, backlog hides done/canceled. Consequence: per-section
counts are now loaded-subset (like views), not per-cycle server counts — the
old per-section paged fetches are gone. ALSO `ProjectDefaultSlot.PLANNING`
(enum-only, no migration): a saved planning view (e.g. cycle-filtered `^PIPE`)
can back `/p/KEY/planning` via the same designation flow + a third row in the
Default-surfaces picker. Board/list builtins remain separate implementations
sharing atoms — full rebase onto the view engine is the designed follow-up;
default-surface designation is the escape hatch meanwhile. 716 tests, tsc
clean, dist rebuilt, :8000 restarted.
**Addendum 6 — cycle-stats scoping bug + surfaces ARE views now.** (a) BUG
(user screenshot): cycle-handle time chips fetched `GET /cycles/{id}/stats`
UNSCOPED, so DEV's planning surface showed PIPE-115's TD estimate/logged
totals (cycles span projects). Fixed end-to-end: the stats endpoint + both
seams (`cycle_state_category_counts`, `cycle_time_totals`) gained
`project_id`; `cycleStatsQuery`/`CycleHeaderStats`/`ViewList` thread a
`cycleStatsProjectId`; project-scoped views pass `view.project_id`, the
planning page passes the project, the workspace cycle page stays unscoped by
design. Audited all consumers (grep cycleStatsQuery/CycleTimeChips): cycle
page + ViewList handles were the only fetchers; done-pills/progress were
already bucket-scoped. Live-verified: PIPE-115 unscoped = 6 items/2w 4d est,
DEV-scoped = 0/0m. (b) USER DIRECTION "why two entities of the same display" —
designation-as-overlay retired in favor of **seeded views**: every project
ships with workspace-visible, admin-editable Board/List/Planning views
(in-txn hook on project.created + backfill migration `62681dd4006c` — TD+DEV
seeded live), `project_default` marks the backer, designated views can't be
deleted (409, swap first), the settings card is now "Project surfaces". The
legacy builtin pages remain only as a no-designation fallback (dead in
practice). 716 tests, head `62681dd4006c`, :8000 restarted, dist rebuilt.
Same-day UX fix (user screenshot: sidebar duplicates + undeletable): surface-
backing views are EXCLUDED from the sidebar's generic per-project view lists
(the static Board/List/Planning entries ARE those views — queue-exclusion
precedent), and the view page swaps the dead Delete button for an emerald
"Project board/list/planning" chip whose tooltip explains the swap-first rule.
**Addendum 7 — designation concept DELETED (user: "I don't like these backing/
referencing ideas or the delete protection — projects just come with default
views; remove code that's no longer useful").** Final model: `seed_project_views`
creates three PLAIN views (Board/List/Planning) per project (hook + backfill
stay); `views.project_default` column DROPPED (migration `004bbb60df13`),
along with ProjectDefaultSlot/SLOT_VIEW_TYPES, the PUT/DELETE project-default
endpoints, all designation guards (delete protection, sharing/type-change
409s), the DefaultSurfaces settings card, `useProjectDefaultView`, and the
surface redirects. The builtin board/list/planning PAGES + their routes are
deleted too (`routes/board|list|planning.tsx`, RoutePath.projectList/planning,
`planningItemsQuery`); `/p/$projectKey` → new `ProjectHomePage` (redirects to
the project's first view; empty-state otherwise); the sidebar lists views
first then Roadmap/Reports/Settings (no static surface entries); ProjectNav =
Roadmap+Reports only; CommandPalette per-project entries = Project + Roadmap;
project-scoped VIEW pages gained the New-item button + `c` hotkey (they were
on the deleted builtin pages — creation UX preserved). Seeded views are
deletable (a project can genuinely have zero board views if the admin wants).
716 tests (designation test rewritten as the seeding test), tsc clean, dist
rebuilt, head `004bbb60df13`, :8000 restarted.
**Addendum 8 — two-scope settings (spec 67) + duplication sweep.** (a) USER
DIRECTION "instance vs workspace vs project — 3 layers is not useful": the
scalar-settings cascade is now **project → instance** (`SettingScope` lost
WORKSPACE; `resolve()` lost workspace_id — all callers updated; migration
`a7c2e19b4f30` promotes any workspace rows to instance + applied). Settings UI:
**General** tab = the instance-defaults editor ("defaults for every project",
instance-admin gated); **Instance** tab renamed **Server** (deploy/LDAP/SMTP
status only, scalar editor removed). **SLA policies are PROJECT-level now**:
`sla_policies.project_id` NOT NULL (PolicyCreate requires it, workspace_id
derived), list by project, matched_policy = the item's project's policies,
admin page moved to `/p/KEY/settings/sla` ("SLAs" tab); spec doc
`docs/specs/67-two-scope-settings.md`. (b) DUPLICATION SCAN (full report in the
 session log): fixed same-day — `radd/worker.py` PeriodicLoop
replacing 9 copy-pasted dispatcher loops (standardizes restart-safe stop();
webhooks' httpx client now lazily created/closed), dead `BoardColumn.tsx`
deleted, `lib/dates.ts` consolidating 6 shortDate/formatDate/relativeTime
copies (FIXES a real my-work timezone bug — unanchored date-only parse),
`AssigneeAvatar` now wraps the shared `Avatar` (custom avatar colors/emoji
finally show on rows/cards), stale ViewSwimlanes docstring. DEFERRED (M
effort, recommended): shared outbox-consumer skeleton (3 verbatim head-seeded
copies: csat/googlechat/mailintake-outbound + 2 partial), `useBucketDrop()`
hook for the 3 DnD wirings, `<QueryError>` for ~28 inline error boxes,
web `lib/duration.ts` hardcodes 8h/day while the server setting is per-project
(latent timesheet display divergence). Googlechat dispatcher gate deliberately
left as-is (url-only, no run_workers — flagged). **716 tests**, head
`a7c2e19b4f30`, dist rebuilt, :8000 restarted, smoke-verified (project SLA
list + instance settings live).

**Addendum 9 — global scope + all deferred consolidation done (spec 67 as-built
follow-up).** (a) `timelog_hours_per_day` is INSTANCE-ONLY now (scopes=(INSTANCE,),
per-project resolution removed, migration `c4f8a25d91e7` deletes stray project
rows; `resolve()` defensively filters lookup scopes by the spec). `GET /instance`
(+ login-options) exposes `timelog_hours_per_day`/`timelog_days_per_week`; web
`duration.ts` takes a DurationConfig + `useDurationConfig()` hook — the
hardcoded 8h/day is GONE (timesheet + HistoryTab thread it; other surfaces
render server-formatted strings). (b) SCOPE VOCABULARY: `PermissionScope.GLOBAL
= "global"` (wire value changed; web mirror updated; roles matrix says "Global
permissions"), `authz.global_scope_permissions`, `perms.global(...)` (29 call
sites), catalog descriptions + ~25 UI strings swept "workspace"→"global" WHERE
IT MEANT SCOPE — the workspace ENTITY keeps its name everywhere (workspace_id,
tables, memberships, `workspace.manage` atom keys stay: stored in role rows,
resource=entity). (c) ALL DEFERRED TASKS: `events/runner.py`
`run_head_seeded()` replaces the 3 verbatim consumer skeletons (csat/googlechat/
mailintake-outbound; googlechat delivery now correctly after cursor commit;
search/notify/automations left — real semantic differences), googlechat
dispatcher now gates on `run_workers` too, web `lib/bucket-drop.ts`
`useBucketDrop()` replaces the 3 copied drop-target wirings (+ fixes stale
hover on cancelled drags), `components/QueryError.tsx` replaces 28 inline
error boxes. **716 tests**, head `c4f8a25d91e7`, dist rebuilt, :8000
restarted, smoke-verified (/instance fields + permissions scopes=global|project).

Row-alignment polish (user screenshot): queue meta columns are FIXED-width now
(reporter w-36 truncate, age w-11 right, SLA chip in a w-24 slot rendered
empty-or-chip), the optional list-row sla slot got the same fixed wrapper, and
unassigned rows render `UnassignedSlot` — an avatar-sized dashed "—" circle —
so the priority/assignee/state columns never drift (CardSlots assignee slot:
avatar OR placeholder). Labels column too (user follow-up): row titles are now
the ONE flexible cell (`flex-1 truncate` — the "max summary length" is
responsive, not a char cap) and labels render in a fixed `w-56` right-anchored
column (present even when an item has no labels; `LabelChips nowrap` clips a
single line, +N tooltip carries the rest) — applies to list/queue/planning
rows via the shared ListRow; board cards keep wrapping (vertical layout).

**Page-level SLQ filter bar (rounds 14+15 — spec 55, LIVE).** The list
route's ad-hoc SLQ bar is a shared affordance on every content page, mounted right
under each page's filter controls: board, list, cycle, planning, roadmap, and saved
views (under the quick-filter chips). Pieces: `lib/slq-filter.ts` (`useSlqPageFilter`)
+ `components/views/SlqFilterBar.tsx` (SearchCode icon + compact `SlqEditor` +
`AskAiBar`). **Round 15 rework (scale): typing VALIDATES, Enter EXECUTES.** New
backend `GET /items/slq/validate` (parse + compile — field/label resolution only,
zero work_items I/O; 422 {detail, position} incl. did-you-mean) behind
`service.validate_slq`; `useSlqValidation` in hooks.ts replaced the old live-execute
`useSlqProbe` EVERYWHERE (page bars, ViewModal + quick-filter chip rows, automation
RuleEditor) — no surface executes SLQ speculatively anymore; match counts appear only
after a committed run. Status line gained a `ready` state ("Valid — press Enter to
run"); NL→SLQ "Ask" commits its query immediately. Editor Enter semantics (Jira
rule): Enter accepts a suggestion only after arrow/hover navigation, otherwise runs;
Tab always accepts; Esc now also cancels a still-debouncing suggest request (fixed
the reopen-after-Esc race). Semantics: list swaps to the server result (honors ORDER
BY, offset-paged Load more via `infiniteSlqItemsQuery`); other pages intersect by id
— scoped `project_id` (board/planning/roadmap), `cycle_id` (cycle page, ANDs
server-side with `q`), view's project or workspace (views). Cycle-page stats fall
back to client-side counts while a query is active; empty states distinguish "no
items" from "no matches". **Pagination everywhere (round 15):** board + roadmap moved
to `infiniteItemsQuery` (Load more footer/link), saved views to
`infiniteViewItemsQuery` (Load more strip; CSV exports loaded+filtered set), planning
sections offset-paged per section (backlog Load more), committed list-SLQ results
paged. `item-mutations.ts` patches the paged caches (`mapPages`/`transformPages`
helpers): move/update/star/reorder all optimistic against `InfiniteData<Item[]>`;
`useMoveItem` patches flat + paged project caches. Intersection match set stays one
200-item page — "N+" flags the cap. Verified via Playwright with network
interception: 0 item-executions while typing (1 validate call), exactly 1 execution
on Enter, Load more on list/board/view/planning, arrow+Enter accepts, board drag
optimistic through the paged cache (reverted). 621 pytest green; :8000 restarted.

**Co-ownership + ownership transfer (round 18 — spec 57 cont., LIVE).** ShareLevel
gained **`owner`** (co-ownership: full control — edit/re-share/delete/transfer; grantable to
people or teams, NEVER valid for workspace_access → 409) and **`POST /views/{id}/transfer`**
(owner/co-owner reassigns owner_id; target needs item.read in scope → 409; target's redundant
grant rows dropped; PREVIOUS owner auto-kept as editor — no accidental lockout). Validation order:
invalid workspace_access rejects before the broadcast-permission check. UI: "co-owner" in the
grant-level selects + "Transfer ownership to…" in the modal's Sharing section (applied LAST on
save — after the sharing PUT, since manage rights may vanish the moment it lands). No migration
(level is a string col). 625 pytest (+co-ownership/transfer matrix); live-verified: co-owner
re-shares (200), workspace_access=owner 409, transfer → old owner editor (can_edit true /
can_manage false / delete 403), new owner deletes (204). QA user cleaned.

**View ownership + sharing (round 17 — spec 57, LIVE, `docs/specs/57-…`).**
Sharing no longer surrenders ownership: `views.owner_id` = creator in every mode (NULL only on
legacy pre-57 rows → view.* atoms manage those); NEW `view_shares` (user XOR team + ShareLevel
viewer|editor, FK CASCADE, merge-inventory dedupe) + `views.workspace_access` (level every member
gets, NULL = not workspace-visible; migration `5e4a41d09ca0` backfills legacy shared → 'viewer').
Visibility = owner ∪ grantees (direct/team) ∪ members when workspace_access — others 404, ADMINS
INCLUDED; editor grantees edit the definition; re-share/delete = owner only. `PUT
/views/{id}/sharing` full-state replace (owner-gated; enabling workspace_access needs view.create
— broadcast bar; user/team shares need only item.read, so members share personal views freely).
`ViewRead`: `owner` ref + `workspace_access` + `shares[]` + per-actor `can_edit`/`can_manage`
(server-computed). Frontend: `ViewSharingEditor` in the view modal (workspace-access select +
person/team rows w/ levels, owner-only), view page gates Edit/Delete on the server flags + "by
{owner}" chip. `ViewCreate.shared` stays as alias (viewer) so demo_views.sh keeps passing. 624
pytest green (+test_view_sharing.py matrix); live-verified with a scratch member: team-gated
visibility (join team → appears, revoke → vanishes), viewer 403/editor 200, owner-only re-share,
member broadcast 403, admin CANNOT delete a member's personal view; UI create/edit round-trip.
QA artifacts fully cleaned. NOTE: "share a personal WIKI space" (user mentioned) is NOT covered —
doc spaces have no ACLs yet; the view_shares pattern generalizes if wanted.

**Cycle regex filter + stint history (round 16 — spec 56, LIVE, `docs/specs/56-…`).**
(1) `views.cycle_filter` is now a REGEX (was glob): case-insensitive unanchored, `re.compile`-validated
on save (409), matched client-side (`matchesCycleFilter`); ViewModal shows the field with live
invalid-regex feedback + save gating and now ALWAYS for planning views (they're implicitly
cycle-grouped — before, planning views couldn't set a filter at all). (2) **Item↔cycle stint
history**: `item_cycle_records` (cycles module, migration `c536f26534fb`) — one row per visit,
`removed_at` NULL = open; items service records on every cycle change (create+update — carryover
moves route through update); `ItemRead.past_cycles` (closed stints, deduped) renders as
"Previously in …" chips under the issue rail's Cycle picker; **SLQ `past_cycle`** queries closed
stints (`past_cycle = "PIPE - 115"`, `IS NOT EMPTY` = rolled over; current cycle deliberately
excluded — that's `cycle`); autocomplete + cheat sheet updated. Backfill: migration seeds open
rows; `scripts/backfill_cycle_history.py --apply` RUN on live (mined events; **294 PIPE-116/117
stints unrecoverable — those cycles were DELETED from the workspace; deleting a cycle
CASCADE-drops its history, complete instead of delete going forward**). 623 pytest green
(+test_cycle_history.py); Playwright-verified (regex view `^TS`, modal invalid-regex gate,
carryover chip on TD probe item, past_cycle autocomplete); QA artifacts deleted; :8000 restarted.

**Configurable screens (spec 53) — NEW module, first slice shipped.** Field-layout
config per (project, issue-type): `screens`/`screen_fields` (migration `1ec5ca425fcd`),
`GET /screens/effective` (resolve = issue-type → project-default → built-ins; builtins
default primary, **custom fields default secondary** so the noisy tail collapses in the
peek with zero config), `GET/PUT /screens` (project.manage). `IssueProperties` renders
fields individually by placement — primary shown / secondary under a collapsible "More
fields" (collapsed by default in the peek panel) / hidden omitted; editor at project
settings → **Screens**. Next slices: card display (board/list) driven by the same config;
finer builtin grouping. **UI polish this pass:** the sidebar hides completed cycles behind
a "Show completed (N)" toggle; **full-width sweep** — every view/settings page now fills
the pane instead of sitting in a centered `max-w-*` column (removed `mx-auto max-w-*` from
the shared `SettingsPage` wrapper + cycle/projects/inbox/my-work/reports/workspace-reports/
issue-page/wiki-page; docs-index grid widened). Only the login card and the public
form-submit page stay intentionally narrow-centered (focused forms).

**Active thread — a settings/UX polish pass (specs 50-52 "Known follow-ups"):**
1. ✅ **Field default values** *(was the one explicitly missed)* — `default_value` (nullable JSONB,
   migration `bb706d3802ae`) on custom-field defs, validated against type/options on create + `PATCH`;
   `apply_defaults` seeds it onto items that omit the key (explicit null preserved); inline editor in
   the fields settings panel + the New-field modal, both reusing `CustomFieldControl`.
2. **Comprehensive settings-UI pass** — shipped: dismissible info banners + value-chips
   (Type/Priority/State) + up/down reorder on the config editors, **+ inline default-value editing
   (done, item 1)**. Still to do: the slide-in "Create new / Use existing" add panel, and sweeping the
   *remaining* settings pages into the same OtherTracker-style design language.
3. **Spec 50/51/52 follow-ups** — ✅ `timelog_hours_per_day` into the scalar cascade (now resolved
   per item project like `work_week_days`); ✅ issue-mention backlinks (`ItemLinkType.mentions`
   auto-derived from `#[…]`, read-only Mentions section on the item view). Still open: builtin-field
   READ blanking on reports/FTS/MCP surfaces (item hydration done); scoped-settings audit events;
   workspace-level custom-role assignment (long-standing spec-36 gap); Priority/State letter-chips in
   *list rows* (rail done); `comment_counts` accuracy for team-restricted internal comments.

**Then** adoption + the pre-OSS checklist (§8): real AD login, replace the real-content sample data
with synthetic, trademark/security pass.

### Operational notes for a fresh session
- **Restart the server after backend changes** (no `--reload`). Kill by PID, NOT `pkill -f` —
  the kill command string self-matches and kills the tool shell:
  `PID=$(ss -ltnp | grep ':8000' | grep -oE 'pid=[0-9]+' | cut -d= -f2); kill $PID`, then
  `cd server && setsid nohup uv run uvicorn --factory radd.app:create_app --host 0.0.0.0 --port 8000 > var/server.log 2>&1 &`.
- **Alembic autogenerate ALWAYS proposes to drop `ix_doc_pages_fts`** — a false positive (functional
  GIN index it can't introspect). STRIP that line from every generated migration or docs search breaks.
- **npm is not preinstalled, but node + network ARE** — bootstrap npm from the registry when you need
  to add a dep: `curl -s https://registry.npmjs.org/npm/latest | node -e '…dist.tarball…'`, download +
  `tar xzf`, then `node <extracted>/package/bin/npm-cli.js install …` against `web/`. (This is how
  `@milkdown/crepe` + react-markdown got in — the old "no package manager" blocker is gone.) For plain
  builds still use `web/node_modules/.bin/{tsc -b, vite build}` directly. dnd-kit is NOT installed.
- **Rich text = Milkdown/Crepe for BOTH read and edit (spec 54 + unification):** the
  user's directive: ONE consistent engine, "good clean feature-rich viewing + editing like Jira/
  OtherTracker" — no variant splits, no separate read renderer for rich surfaces. **Edit:**
  `editor/RichEditor.tsx` — every editor (description, comments, wiki) gets the SAME fixed TopBar
  (heading selector trimmed to P/H1–H3), `/` BlockEdit menu (h4–h6 nulled) + block drag handle,
  table widget; floating selection Toolbar off; ImageBlock gated on `onUploadImage` (feature-flag
  cascade auto-hides its TopBar//-menu items). **Read:** `editor/RichViewer.tsx` — the SAME Crepe in
  `setReadonly(true)` with all chrome features off, so content is pixel-identical read vs edit
  (headings, tables, code blocks incl. copy button, images). Used via `LazyRichViewer` (same lazy
  chunk + an IntersectionObserver that mounts instances only near the viewport — issues carry up to
  ~236 comments; raw-markdown placeholder holds layout) in item description, comment bodies, doc
  pages; existing pencil-icon flows switch to the editor. `lib/markdown.tsx` (react-markdown) remains
  ONLY for small previews (AI summary, doc history). **Shared chips:** `editor/chips.ts`
  `mentionChipsPlugin` decorates `@[Name](uuid)` / `#[KEY](KEY)` tokens as colored pills in BOTH modes
  and routes clicks via `handleDOMEvents.click` (NOT `handleClick` — that fires on mouseup, too late
  to cancel an anchor's native navigation; this bug was caught by the Playwright smoke). Read mode:
  issue chips navigate, external links open a new tab; edit mode: chip clicks are consumed. One
  typography scale for both in `rich-editor.css` (theme's 42px h1 → 22/18/16/14) + table-widget
  calming (no fade-lag, tightened + hover-bridged action popup). `@`/`#` autocomplete unchanged
  (`editor/mention.ts` + portaled popup; `#` opens immediately with hint/searching/no-match rows;
  bare-number queries match key numerics server-side via `search/service.py key_pattern`).
  Verified with Playwright chromium (scratch venv; browser cached): 4–23 viewers/page, chips render +
  route, contenteditable=false, h1=22px, composer TopBar present, zero console errors. **Note:** a
  Tiptap trial was reverted back to Milkdown — no `@tiptap/*` remains.
- **Editor: plain-text mode + `/` quick actions (GitLab-inspired):** every RichEditor has
  a footer bar — "Switch to plain text editing" toggles `editor/PlainEditor.tsx` over the SAME value
  (`radd.editor.plainText` localStorage pref, sticky across editors/sessions; Crepe reseeds from the
  live markdown on switch-back) + an M↓ badge. Plain mode is FEATURE-PARITY, only the rendering is
  plain (user directive): its own markdown toolbar (H1–H3/bold/italic/strike/code/link/lists/task-
  list/quote/code-block/table/divider + image when upload is wired; selection-aware wrap/line-prefix-
  toggle edits), the SAME `@`/`#`/`/` popups (shared TRIGGER_RE/SLASH_RE from mention.ts; caret
  coords via the mirror-div trick; tokens spliced as literal markdown, slash commands removed+run via
  `PlainEditorApi.replaceRange`), and paste-image upload. Crepe's BlockEdit slash menu is OFF for good (it
  only duplicated the toolbar's inserts); `/` at block start now opens a QUICK-ACTION menu that acts
  on the ISSUE in context (`editor/mention.ts` gained the `/` trigger; `items/quick-actions.ts`
  `useIssueQuickActions` builds the entries: Assign-to-me/Unassign/Assign:<user>, State:<s>,
  Priority:<p>, Add/Remove label:<l> via the normal PATCH path, plus every enabled MANUAL automation
  as a custom action → POST /automations/{id}/run). Token-filtered ("/assign hus"), Enter runs +
  removes the typed command, no issue context (wiki/new-item) → `/` inert. Extensibility: custom
  slash actions = manual automations (settings rule builder now offers the Manual trigger; extensions/
  MCP create rules via REST). Verified end-to-end on a throwaway :8002 server + Playwright (assign,
  automation-run → priority=blocker, plain-toggle roundtrip, cleanup). NOTE: needs the :8000 restart
  to go live (runnable/run endpoints + MANUAL enum are backend changes).
- **Planning as a VIEW TYPE + quick filters:** `ViewType.PLANNING` — creatable like
  board/list (New-view modal option), workspace-spanning or project-scoped, with the full SLQ
  filter; rendered as cycle-grouped ViewList sections (the spec-23 cycle axis does the work: staged
  cycle headers with dates/progress + Backlog bucket + spec-24 cross-bucket drag), stored axes
  ignored. **Quick filters (Jira-style)** on EVERY view type: `views.quick_filters` JSONB
  [{name,query}] (migration `7ec22a4a1c25`), each chip's SLQ compile-validated on write (ORDER BY
  rejected 409 — chips are conditions only); the view page renders a chip row, active chips
  parenthesized-AND into the query (`combineQueryWithFilters` keeps the base ORDER BY at the tail)
  and the ENTIRE machinery (fetch + optimistic drag/star/reorder caches) targets the filtered
  dataset via an `effectiveView`. Verified live: workspace planning view with TD/DEV/"Mine"
  (`project = TD` etc.) chips filtering correctly; test view deleted. The standalone
  `/p/$key/planning` page stays as the zero-setup per-project surface.
- **Polish batch (the "Jira replacement people would want" pass):** (1) **server-side
  cycle filter** — `GET /items?cycle_id=` (UUID-or-`none` = backlog, same idiom as assignee/team);
  the cycle page now does ONE paged server-filtered fetch (`cycleItemsQuery`, up to 2000) instead of
  per-project pages client-filtered (which silently truncated 330→69). (2) **Planning view**
  (`/p/$key/planning`, sidebar + ProjectNav entries): backlog (cycle=none, done/canceled hidden)
  beside active/upcoming/draft cycles as native-DnD drop targets — drag a row to (re)assign its
  cycle via the normal PATCH path; counts are server-real. (3) **Notification prefs** —
  `notification_prefs` (migration `9a829dc79eef`): per-type mutes filtered in the notify consumer +
  an email-digest opt-out honored by the emailer (rows still stamped so the backlog drains);
  `GET/PUT /notifications/preferences` + a Notifications section on /settings/profile. NOTE: bulk
  cycle moves never notified anyway (planner only reacts to state/assignee/description). (4)
  **Migration fidelity** — Jira ATTACHMENT import: `jira_export_build` records per-issue
  {filename,url}, new `jira_fetch_attachments.py` downloads them (resumable, Bearer PAT), and
  `import_jira --attachments-dir` uploads per item + rewrites `!file!` embeds to real
  `![name](/attachments/id)` markdown (`jira_markup.replace_attachment_embeds`, tested) in
  descriptions (post-upload PATCH) and comments. **USER MERGE**: `POST /users/{id}/merge`
  (instance-admin) folds a duplicate identity — explicit table inventory in `auth.service.merge_users`
  (repoint / dedupe-composite / purge-credentials lists — KEEP IN SYNC when new tables reference
  users), source deactivated + `user.updated {action: merged}` event. No UI affordance yet (API
  only) — follow-up. (5) **Obsidian-inspired dark theme** — the stock blue-black zinc scale remapped
  to neutral lifted grays (#1e1e1e page family) via the same Tailwind-v4 variable seam as the light
  theme (zero component changes); `rich-editor.css` converted from hardcoded hexes to
  `var(--color-zinc-*)`, which also fixes the editor being a dark island in LIGHT mode; sky-300
  added to the light remap for issue chips. All verified on a throwaway DB
  (radd_qa_batch, dropped) + live screenshots; 621 tests.
- **Cycle management, Jira-style (two passes — the project language is CYCLES, never
  "sprint", per user):** `POST /cycles/{id}/complete` closes a cycle mid-window
  (`cycles.completed_at`, migrations `bda2d16f2533`+`5df5c6f35ec7`; `cycle_status` is
  completed_at-aware) moving open items to a chosen cycle or backlog (items seam
  `move_open_cycle_items`, per-item update_item as the caller) and optionally starting the target
  (length inherited from the closed cycle). **Recurring series** (user rework of the first
  workspace-setting approach — REVERTED from the scalar registry): per-LABEL `cycle_series` rows
  (label/drafts_ahead/next_number, membership by name via `parse_cycle_name`), created from the
  New-cycle modal's "Recurring cycle" checkbox (bare label + starting number = Jira-import
  continuity, e.g. begin at 120), managed in a "Recurring series" section on /settings/cycles
  (edit look-ahead + next number, delete = stop recurring); provisioning tops each label to N
  future cycles, skipping taken numbers. Complete-modal targets are SAME-LABEL future cycles.
  **Cycle page**: stats header (`GET /cycles/{id}/stats` — per-category counts + estimate/logged/
  remaining totals via items+timelogging seams) + person/team filters that drive BOTH the stats
  (server params) and the list (client filter); the progress bar now uses stats (the per-project
  item queries are paginated — the list can be a subset, stats never are). **Scheduled cadence
  (third pass, migration `229e9d3c413b`):** series optionally carry start_weekday (0=Mon) +
  duration_days — provisioned cycles then arrive with real timelines (pure `series_windows`:
  chained back-to-back after the label's latest scheduled end, starts snapped to the weekday;
  stale chains restart from today), existing dateless drafts get scheduled when a cadence is
  added, and a recurring create with no dates self-schedules ("2-week Mondays" = weekday Mon +
  14d). UI: "Starts on"/"Duration (days)" in the New-cycle recurring section + editable cadence
  per series row (Unscheduled clears via explicit nulls). Verified end-to-end on
  a throwaway server (recurring create → QAS-51/52 + series next=53; stats est 2d/logged 4h/
  remaining 1d 5h; filter→0; complete → same-label move + QAS-53 top-up; bare "QAX"@120 →
  QAX-120) with full cleanup; live :8000 restarted. NOTE: the user completed the real PIPE-116 →
  117 with this flow same-day.
- **Time-tracking polish:** the peek drawer's rail renders `TimeTrackingPanel` with
  `compact` (totals + bar + "Estimate: X · N entries" line only — no log form, no worklog list; the
  full page keeps everything). BUG FIX: `format_duration` floored negatives to "0m", so an over-
  logged item's remaining ("estimate − logged") rendered as "0m over" — negatives now keep their
  magnitude ("-2h 45m" → UI "2h 45m over"); pinned in test_timelog_duration.py. Backend change →
  needs the :8000 restart.
- **Peek vs direct navigation:** issue keys are REAL links everywhere —
  `ItemBadges.ItemKeyLink` (a TanStack `Link` to `/issues/$itemKey`, `stopPropagation` so the row's
  peek handler doesn't fire; middle/ctrl-click new-tab works since it's a true anchor). Rule: click
  the KEY → full issue page; click the card/row BODY → `?peek=` side panel; the peek header's key
  also expands to the full page. Wired in: BoardCard, list.tsx table rows, ViewList rows, cycle rows,
  My-Work rows/recent-chips/notifications, roadmap label rows + UnscheduledTray. Rows that were
  `<button>` wrappers became `div[role=button]` (anchors can't nest in buttons). Timesheet label
  stays peek-only (it's the only click surface there). Verified with Playwright: key→/issues/KEY,
  row→?peek=, no page errors.
- **Markdown rendering (read mode):** `lib/markdown.tsx` `Markdown` = **react-markdown + remark-gfm**
  (remark is the same parser Milkdown serialises to). React elements only (no innerHTML). Custom tokens
  via `remarkRaddTokens`: `@[Name](uuid)`→mention chip, `#[KEY](KEY)`→`/issues/KEY`, and `<br>` in table
  cells → real line breaks. Removed the old `renderInline`/`parseBlocks` parser + dead
  `MarkdownEditor.tsx`. Still deferred: light-theme tint; converting the small settings textareas
  (canned/automation/release).
- **Jira backwards-compat (extended same day):** imported comments/descriptions are stored
  in Jira wiki markup. `lib/jira-markup.ts` `jiraToMarkdown()` (+ the backend twin
  `scripts/jira_markup.py` — KEEP IN LOCKSTEP, same rules/order; parity-checked over shared fixtures)
  converts it to markdown; the **viewer** applies it before rendering and the **editor** on seed, so old
  Jira content renders + edits correctly without a bulk migration. Full rule set now: links/bare-URLs,
  `[~user]`, `{quote}`/`{panel}` (→ blockquote, `title=` bolded), `{code}`/`{noformat}` (params cleaned
  to a language), `{{mono}}`, `hN.`, `||header||`/`|cell|` tables → GFM (headerless promotes row 1),
  `#`/nested `*#` lists, `*bold*`, `-struck-`, `{color}`/`{anchor}`/`{toc}` stripped, `!img.png!`
  embeds (URL → real image; filename → `*(image: …)*`, attachments were never imported), emoticons →
  emoji. Ambiguous rules (bold, `#` lists, strike, emoticons) collide with native markdown, so: the
  frontend gates everything on `HAS_JIRA_RE` (unambiguous-marker sniff), the importer converts
  unconditionally (`assume_jira=True` default), and `fix_jira_markup.py` back-fills with
  `assume_jira=False` (gated; `--assume-jira` lifts it for all-Jira DBs). Invariants pinned in
  `server/tests/test_jira_markup.py`. Live-DB dry run: 11 451/28 428 comments +
  1 035/3 281 descriptions would convert, samples clean — `--apply` (writes a rollback file) is
  **pending a user decision**; render-time conversion already fixes display either way.
- Verify pattern that works: throwaway server on an alt port + curl cookie jars (see the session log);
  the live `:8000` + its dev data should stay untouched, and any test rows created must be cleaned up.
- Frontend-only changes need only a browser hard-refresh (the running server serves `web/dist` live);
  backend changes need the restart above.

## Addendum 10 — spec 87: directory-owned teams, per-team delegation, grants that grant

User direction: AD-linked teams must be **read-only from AD** (mixed local/synced
membership "gets messy really quickly"); local teams may still contain AD users; not
everyone may create/edit teams, but a **team leader needs a per-team grant** to manage
only their own team. Follow-up direction in the same session: fix the dead global-grant
path **and audit for any other dead or useless grants**. Full detail:
`docs/specs/87-directory-teams-and-real-grants.md`.

**The audit reframed the work.** Cross-referencing every `Permission` against every
`authz.require` found that *all 47 global-scope atoms were undeliverable*:
`global_scope_permissions()` read `users.instance_role` alone and roles attach only to
projects, so no non-admin could ever hold `label.create`, `team.update`, `sla.*`,
`cycle.*`, `role.*`, `user.*` … while the roles matrix advertised every one of them.
That is also why the user's actual request could not be met by granting a lead
`team.update` — it had no delivery mechanism, and would have granted *every* team.

- **`global_role_grants`** (`auth/grants.py`): a role held instance-wide by a user or a
  team (`view_shares` shape, CHECK-constrained). Applies at **both** scopes — global
  checks union it in and every project treats it as one more granted role, so
  project-scoped atoms inside a globally-granted role are not a new dead grant.
  `GET/PUT /roles/{id}/global-grants` (full replace, `role.update`-gated — which is
  escalation-equivalent to admin, documented as such). `/auth/me` now returns
  `effective_permissions()` so grants reach the SPA's gates.
- **Atoms dropped:** `user.delete`, `import.run` (no endpoint could exist),
  `dashboard.update`/`dashboard.delete` (spec-57 ownership decides). Migration
  `3a363a121502` strips them from stored role JSONB — `RoleRead.permissions` is
  `list[Permission]`, so a stale string would 500 `GET /roles`.
- **Endpoints built** for atoms that had none: `PATCH`/`DELETE /labels/{id}`,
  `DELETE /states/{id}` (409 if default or occupied), `DELETE /fields/{id}`,
  `DELETE /webhooks/{id}`, `DELETE /teams/{id}` (409 while attached to a project — this
  closes the "teams have no DELETE endpoint" follow-up from spec-57 QA above).
  `PATCH /users/{id}` honors `user.update`, with `instance_role` kept hard-admin.
- **`teams.source`** (`TeamSource` local|directory): membership 409s on a directory team,
  enforced in the service. Linking re-sources the roster to `directory` (nothing frozen
  outside the sync's reach), unlinking to `manual` (the escape hatch — no access lost).
  Name + project grants stay local by design.
- **`teams.owner_id` + `team_managers`:** a team leader administers ONE team — roster +
  rename — but cannot appoint managers, transfer, delete, or attach the team to a
  project. **A leader decides who is on their team, never what their team is entitled
  to.** `MeRead.manages_teams` gates the Teams nav (delegation is invisible to the
  permission union).
- **Stale-group guard:** an empty AD member search is ambiguous (empty vs. renamed /
  deleted); believing the latter revokes everything the team grants. `reconcile_team`
  confirms the DN resolves, raises `StaleDirectoryGroup`, and sets
  `teams.directory_missing_since`; while set, the login path holds removals too, so the
  team cannot be drained one sign-in at a time around the periodic guard.
- **A broken link does NOT unlock the team** (user direction, same day): read-only stands
  as long as the link exists — a missing group keeps its people and stops every removal,
  but re-opening editing is a deliberate unlink, never inferred from a directory the
  server may be misreading. Amber `AD group missing` badge on the row + a one-click
  "Unlink and edit here" banner. Required making the signal trustworthy: `get_group()`
  returned `None` for a dead DC and for a genuine not-found alike, so it now raises
  **`DirectoryUnreachable`** for the former (incl. the eager `auto_bind` in
  `service_connection()`, which sat outside the try) — an outage records an error and
  touches nothing instead of flagging healthy teams.

**Runtime state:** alembic head `78c86f700dbe` (chain `466eca47eeee` global grants →
`3a363a121502` atom strip → `78c86f700dbe` team source/ownership/managers); **824** core
tests green; `web/dist` rebuilt (tsc clean). Verified end-to-end on a throwaway
`:8099` server: the two live AD-linked teams migrated to `source=directory` and now 409
on a manual member add; team create/managers/transfer/delete and the global-grants PUT
all round-trip. `alembic check` still reports only the long-standing `ix_doc_pages_fts`
false positive (alembic cannot see expression indexes).

## Addendum 11 — spec 88: AD import conflicts (flag duplicates, overwrite or merge)

User direction: importing AD users must **flag duplicates already in the system** and offer
to **overwrite or merge, keeping the AD entry** — "essentially update the users list from AD
and merge conflicts, asking whether or not to overwrite; it should overwrite email and such."
Detail: `docs/specs/88-ad-import-conflicts.md`.

**Why it mattered:** Radd identifies people by EMAIL and accounts arrive from several places
(Jira importer, local signup, OIDC, an older mail domain). `find_or_create_user` matched on
email alone, so importing `jsmith@corp.example` while the same human sat there as
`jsmith@old-domain.example` minted a SECOND account and split their history — and reported it as
a clean `created: true`. Note Radd has **no username column**: a sAMAccountName can only be
compared against an existing email's LOCAL PART, which is what "duplicate username" means here.

- **Preview first.** `POST /ldap/directory-users/import/preview` runs the PURE
  `plan_user_import` over the selection × the existing roster → `new` | `linked` | `conflict`,
  each match carrying WHY it matched (email / username / name). Nothing is written.
- **Then resolve.** The import endpoint takes a per-entry `ImportResolution`:
  **overwrite** (one account takes AD's email/name/source — **`id` preserved**, so every issue,
  comment and worklog stays attached; 409 instead of stealing an email another account holds),
  **merge** (fold the look-alike into the AD-identified account via `auth.merge_users`, survivor
  takes AD's values), **create** (they really are two people), **skip**. No resolution = the
  pre-88 create-or-link behavior, so the endpoint stays backward compatible.
- **Nothing auto-resolves.** A name collision is a heuristic and rewriting someone's email
  address is not inferable — the preview only *suggests* (merge when both accounts exist, else
  overwrite) and a human confirms. The review UI spells out each consequence in plain language.
- **Known consequence to flag when using it:** overwrite sets `source=ldap`, so a previously
  local account becomes directory-governed — the user sync may rename it and, with
  `ldap_user_sync_deactivate_missing` on, deactivate it when the person leaves AD. The password
  hash is deliberately kept (no mid-migration lockout).

**Runtime state:** no migration (behavior + endpoints only); **837** core tests green;
`web/dist` rebuilt (tsc clean). Verified against the live dev DB on a rolled-back transaction:
a legacy `@old-domain.example` account reporting a real issue was classified `conflict`/`overwrite`,
and after applying it the same row carried the AD address with the issue still theirs.

**Why "Sync users" looked broken (diagnosed):** it wasn't. The pass returns
0/0/0 because (a) all 1029 AD users already have accounts, matched by email, so there is
nothing to provision, and (b) the name-refresh step only touches `source=ldap` accounts —
but **1012 of those matches are `source=local`**, created by the Jira importer. So the sync
is structurally inert for ~98% of the roster. A toast reading `0 · 0 · 0` gives no hint why.

**Live-instance shape:** 1293 Radd accounts vs 1029 AD users under
`OU=Sites,DC=ad,DC=studio,DC=com` — 1029 exact-email matches, 27 name-only duplicates
(25 `@example.com` Jira placeholders + 3 `adm-*` aliases; 26 own no work), and 237 with no
AD counterpart (188 own work — leavers/sister studios, never delete; 49 empty, incl. service
accounts `automation@example.system` and `puppetuser@`).

**`scripts/reconcile_ad_users.py`** (spec 88) is the one-off cleanup: buckets every account
ENFORCE / MERGE / KEEP using the same planner as the interactive import, dry-run by default,
`--apply` writes a timestamped JSON audit of every touched account's before-state.
`--enforce-only` / `--merge-only` / `--exclude EMAIL` for control. KEEP is never touched.

**Hazard found while diagnosing — do NOT enable `ldap_user_sync_deactivate_missing` yet:**
49 active `adm-*@ad.example.com` accounts are outside the enumeration (privileged accounts
outside `OU=Sites` and/or lacking `mail`, provisioned by LDAP *login* via the synthesized
UPN), so the departure sweep would read all 49 as gone and deactivate them. Confirmed the
same humans appear in the enumeration under their real mail (`adm-a-user@ad.example.com`
vs `a-user@example.com`), so email-keyed matching cannot see they are present.

**RECONCILE APPLIED** (`--apply --exclude-prefix adm- --exclude alias-user@example.com`;
DB snapshot first at `server/var/backups/radd-pre-reconcile-20260724.dump`, audit at
`server/scripts/reconcile_ad_users_20260723T213102Z.json`): **1011 enforced, 24 merged.**
Result: `source` mix went 1226 local / 66 ldap → **215 local / 1077 ldap**; **zero active
`@example.com` placeholders remain**; the sync now governs **1028 of 1029** matched accounts
(was 17), so "Sync users" is finally a live operation rather than a structural no-op.
a departed user's 6 items repointed to `a-user@example.com` (both rows inactive — user
accepted merging into a deactivated survivor). `hjarrar@example.com` intact: admin, active,
now ldap. Two deliberate hold-backs: the 27 `adm-*` accounts (user: "I don't need those in
the system" — still present, own no work, never logged in, none are admins → retire when
ready) and `alias-user@example.com`, whose AD `displayName` is literally `adm-alias` and would
have degraded a real name.

**Departure-sweep blast radius after the reconcile: still 49** (32 `@ad.example.com` incl.
the adm-* set, 15 `@example.com`, 2 `@sister-studio.com`) — unchanged by the reconcile
because those accounts were already ldap-source. `ldap_user_sync_deactivate_missing` stays
OFF until they are retired or the search base widens.

**Unrelated test fix in the same pass:** `test_user_sync_base_cascade_override_beats_env`
asserted that NO instance-scope `ldap_user_sync_base` existed, so it started failing the moment
the Directory page saved a real one (`OU=Sites,DC=ad,DC=studio,DC=com` 21:03).
It now clears that key inside its own rolled-back transaction — configuring the product must
never fail its own tests. The live setting was verified intact afterwards.

## Addendum 12 — spec 89: deleting users, with their work reassigned

User direction: *"I want to be able to delete local users, and when deleting them get asked
who should own everything that they did before."* Detail:
`docs/specs/89-user-delete-with-reassignment.md`.

**This reverses spec 87**, which dropped the `user.delete` atom arguing no endpoint could
exist behind it. Wrong call: deletion is legitimate, it just needs the authored work rehomed
first. The atom is back and the CRUD triple for `user` is whole again.

- `GET /users/{id}/content` → what the account owns; `DELETE /users/{id}?reassign_to=…` →
  hard delete. Successor REQUIRED when anything is owned (409), omitted when nothing is, so
  clearing placeholder accounts stays one click. The row really goes — unlike merge (keeps a
  deactivated shell) or `PATCH {active:false}` (revokes access only).
- **Worklogs are deleted, not reassigned** (user decision): crediting a successor with hours
  they never worked would corrupt every timesheet and time report. The dialog states the
  count + total hours before confirming.
- **Deleting exposed three latent MERGE bugs.** Diffing `_MERGE_REPOINT` against the live FK
  graph found `approval_requests.requested_by`, `approval_votes.user_id` and
  `doc_pages.updated_by` missing — FK-blocking for a delete, and silently retained by a
  merged-away account today. Plus `teams.owner_id` (ON DELETE SET NULL) would have orphaned
  owned teams. All four added, fixing merge and delete together.
- **Columns referencing users with NO foreign key** (`events.actor_id`, `notifications.*`,
  `item_watchers.user_id`, `attachments.created_by`, `item_*_links.created_by`) would DANGLE
  rather than error — repointed with a successor, purged/nulled without one.
- `tests/test_user_delete.py` asserts repoint completeness **against the live schema**, so a
  new user-referencing table can't quietly break deletion.

**Runtime state:** no migration (behaviour + endpoints only); **842** core tests green;
`web/dist` rebuilt (tsc clean). Verified end-to-end on a throwaway `:8098` server with
temporary accounts (all cleaned up afterwards): empty account deletes with no successor;
owning account 409s without one and, with one, hands its issue over and disappears;
`user.deleted` audit events recorded both.

**Also found while diagnosing the "Sync users does nothing" report:** the live
instance had `ldap_user_sync_enabled` AND `ldap_user_sync_deactivate_missing` turned ON at
21:35 on. The last sync ran 31s BEFORE the sweep toggle was saved, so it has not
fired yet — but `RADD_RUN_WORKERS=True`, so it will on next server start. Blast radius
re-measured: **49 accounts, ALL dormant** (own nothing, never logged in, and only
`hjarrar@example.com` holds an API token) — 27 `adm-*` plus 22 leavers/service accounts. The
earlier "do NOT enable this" warning is therefore **withdrawn**: enabling it is safe here and
retires the `adm-*` cruft. A third test made the same live-DB assumption
(`test_user_sync_provisions_and_updates_toggle_off` asserted `deactivated == 0`) and now
clears the instance override inside its own transaction — turning a feature ON in the product
must never fail its own tests, least of all the assertion guarding mass deactivation.

## Addendum 13 — spec 90: Jira import wizard (live connection, field mapping, staged import)

User direction: wipe the dev DB and re-import from Jira, but rework the flow — pre-import users
from LDAP, import issues, then RELINK links to the new Radd issues rather than back at old Jira;
and build a wizard that lists Jira projects, sets a JQL filter, loads the result into an inbound
schema, and maps fields to local custom fields (creating them where needed). Detail:
`docs/specs/90-jira-import-wizard.md`. Replaces the offline `jira_export_build.py` +
`import_jira.py` round-trip (scripts kept for CLI; the Jira-markup converter moved to
`radd/modules/jiraimport/markup.py`, the script re-exports it).

New module `jiraimport`, live against Jira Server/DC REST v2 (**PAT or basic auth** — PAT wins
when set). Five phases, all shipped:
- **Discovery:** `GET /jira/status|projects`, `POST /jira/preview` → inferred schema (PURE
  `inference.py`; catalog type beats sample cardinality; noise/builtin/useful bucketing — 321 raw
  DEV fields → ~13 worth mapping).
- **Plans:** `jira_import_plans` + per-field mappings (ignore/map/create/builtin), `suggest`
  (pre-filled grid) + `validate`, CRUD (`plans.py`, `mapping.py` PURE).
- **Runs:** `jira_import_runs` as the live progress bar; `runner.py` calls Radd services directly,
  stages FIELDS→ISSUES→LINKS, commits per page, fires an in-process task, fails interrupted runs on
  startup. Preserves Jira IDs 1:1 + timestamps, imports custom fields/comments/worklogs/cycles,
  resolves parents (`issuemap.py` PURE).
- **Relink pass:** issue links → native Radd links when both ends imported (cross-project via
  key remap) else web-link fallback to Jira.
- **Wizard:** `Settings → Import from Jira` (instance admin) — connect → project+JQL → preview →
  map fields (noise/native collapsed) → run with live progress. User pre-import stays spec 88's
  `POST /ldap/directory-users/import`, which the run screen points at.

The spec-89 user-delete guard earned its keep again: it caught that `jira_import_runs.actor_id`
(a new user FK) needed adding to `_MERGE_REPOINT`.

**Runtime state:** DB WIPED + reseeded (spec-90 request; backup `server/var/backups/radd-pre-wipe-20260724.dump`);
alembic head `359b250bda3a` (`5b7a489f873a` plans → `359b250bda3a` runs); **881** core tests green
(39 new: inference/mapping/issuemap/discovery/runner); `web/dist` rebuilt (tsc clean). **Server
restarted** on :8000 with the new module + `.env` Jira creds — `/jira/*` routes live, verified over
HTTP (status connects as `hjarrar` via basic auth, 42 projects). Live-verified earlier: a
14,540-issue DEV preview + a bounded run importing real issues with 0 errors. `hjarrar@example.com`
(AD login) promoted to admin for testing; 8 leaked `jr-*@example.com` test accounts removed.



## Addendum 14 — specs 101–103: the AI platform + multi-host storage wave

**All three specs shipped, live-verified, and in dogfood** (10 commits,
`a5f0b4c..91a1599` + follow-ups; suite at 1229; `docs/specs/101|102|103-*.md`
carry the full designs).

- **Spec 101 — AI provider registry.** Providers are DB rows with model ROLES
  (`chat`/`embeddings`/`vision`); the client seam (`ai/client.py`) does
  structured output, enum-constrained vision choice, embeddings, and SSE
  streaming. Six feature toggles + per-user editor opt-out; Settings → AI.
  The `local` wire shape SHIPS CPU embeddings in-process (fastembed/ONNX,
  `radd[localembed]`, in the image) — semantic search needs no external model
  server. Live: llm-host vLLM (`gemma-4-31b-it`) holds chat+vision; built-in
  embeddings hold the embeddings role; whole dev corpus embedded ~2min on CPU.
- **Spec 102 — storage rebuilt.** `storage_hosts` rows (proxy|presigned
  delivery; presigned = the network decides who reads a zoned host), the
  routing chain (user_choice / CIDR over `RADD_TRUSTED_PROXIES`-resolved IPs /
  LLM via the vision role), per-attachment spec-92 read grants at the single
  mint chokepoint, polymorphic parents (wiki uploads work), move jobs, orphan
  GC that finally deletes BYTES, blob API for jiraimport. The ask prompt fires
  only when the answer can matter (upload-context simulates the chain per
  content type + caller IP; `preempted_by` names the capturing rule), and
  every read carries `storage_host_name` (grid badges). Two dev Garage hosts
  behind `--profile storage` (localhost:3900/3910, region `garage`,
  `deploy/garage/init.sh`).
- **Spec 103 — editor AI + semantic search.** Crepe's AI feature streams
  server-curated actions (builtins + admin presets) with diff review; OFF is
  byte-identical. pgvector runtime-managed schema + per-model partial HNSW;
  the `ai.embedder` consumer's ONE reconcile sweep = backfill + silent-import
  coverage + model swaps; RRF hybrid `/search`; fused similar/deflect; palette
  Ask mode; MCP `find_items` tool (agents inherit the ranker). **NL→SLQ grew
  up in dogfood**: dialect-aware (`items|worklog` — the timesheet teaches
  `issue.*` delegation), pre-compile VALUE repair ("jimmy" → the real account
  via the autocomplete candidates seam; substitutions reported; SLQ itself
  stays exact), live issue-types/work-categories in-prompt (bugs → `type=Bug`,
  not `kind`), and a `Today is <date>` anchor ("this month" guessed 2025-05
  without it).

**Operational (dev):** host-run server needs `RADD_BACKUP_TOOLS_OPTIONAL=true`
(no pg_dump on host); dev DB container is `pgvector/pgvector:pg16` (reindexed
after the alpine→debian libc change, datcollversion null = no warnings). The
old `attachments.storage` module is gone — hosts.py/clients.py/routing/ own it.

## Addendum 15 — the shell/UX + operations wave (unnumbered + specs 104–105)

**Shell redesign (Cairn-inspired bands, screenshots-driven):** two FULL-WIDTH
bars above the sidebar+content split — row 1 = sidebar toggle + brand + the
query slot + bell + avatar (`TopBar`); row 2 = `PinsBar`: My Work + pinned
tabs (view-type/link icons so they read as NAV) + the ALWAYS-visible New item
button (project-aware: direct inside a project route, a project menu
elsewhere; the view toolbar's own button removed). Sidebar lost its brand
header; `sidebar-prefs` became a `useSyncExternalStore` shared store (toggle
lives in the top bar now — two useState copies would clobber each other).
Pins: `NavPin` = view pins (live-resolved, `KEY · name` disambiguation)
XOR link pins `{path,title}` — ANY sidebar anchor is right-click pinnable
(one delegated handler on the aside; volatile-badge rows carry
`data-pin-label`); tabs get right-click Rename/Unpin (`RenamePinDialog`,
labels in `nav.pins` prefs; three storage generations readable forever).
**Query bar:** Ask mode is the DEFAULT on an empty bar (URL-carried queries
open in SLQ), ⌘I toggles modes bar-scoped. **Inbox peek:** top-bar bell
(badge = the existing unread poll) → right drawer (`InboxPeek`, module-level
toggle à la CommandPalette); a row click marks read + opens the ISSUE peek in
place; `NotificationRow` extracted and shared with `/inbox`. **Peek default
width 1100** (672 stacked the rail ABOVE the description — burying what the
peek exists to show), max 1400. **View pages: ONE header band** (identity +
icon-only share state + SAVED chips + count/knobs); the one-tab `ProjectNav`
is deleted (Reports moved into the ⋯ menu). **Radius scale dialed DOWN**
(md/lg/xl/2xl = 6/8/10/12px — the Dusk bump read too round; rounded-full
untouched; plugin-sdk `--radd-radius*` kept in sync).

**AI UX:** the issue page gained the `AiResultsPanel` — summarize/find-similar
answers open BESIDE the reading column (in former dead space; stacked above
it under @4xl) via an `AiResultsContext` the rail buttons + every read-menu
route through (wiki popover unchanged; transforms still open the editor).
**Unified diff review**: per changed textblock the OLD text stacks above as a
red "−" block and the block itself reads as the NEW text (green, deletions
hidden, insertions emphasized) — presentation-only rework of the diff
decoration plugin; cross-block-boundary fragments deliberately keep
strikethrough. **Editor toolbars**: Crepe tinted glyphs with
`--crepe-color-outline` (our BORDER grey — ~1.5:1) at 24px; now 18px,
secondary-text tint (8:1), accent PILL on active marks (Crepe's top bar sets
`.active` but ships no styling for it — Bold on/off rendered identically).
**SelectField** now converts `<optgroup>` children (the walker silently
dropped groups — the automations trigger dropdown rendered EMPTY; grouped
selects get disabled header rows).

**Plugin gating actually works now:** disabling a plugin previously changed
NOTHING — FastAPI's `include_router` appends `_IncludedRouter` wrappers
(path=None), the old path-prefix unmount filter crashed on them, and the
router's bare `except: pass` swallowed it. Fixes: identity/prefix-aware
unmount, hot enable/disable run `on_startup`/`on_shutdown` (the embeddings
dispatcher kept running), `ai.features.feature_enabled` gates on the kernel
registry (`plugin_loaded()`) so search fusion/storage routing degrade too,
the SPA catch-all 404s unknown `/api/*` paths (JSON) instead of serving
index.html, and every hot-mount failure is LOGGED.

**Specs 104–105 shipped** (see their files): leave + team holidays + the
everywhere away-indicator (`PersonName`/`AwayChip`/Avatar status dot) +
timesheet outlier flags; the admin Monitoring page over the new
`events.service.consumer_status()` seam. New modules `leave` + `monitoring`
(both optional bootstrap). Trigger snapshot 65 → 67.

**Operational:** the automations "0 triggers" report was the optgroup bug —
NOT a registry failure (71 triggers served throughout). `/health` is the real
health endpoint; `/api/v1/health` never existed (its old 200 was the SPA
catch-all wart, now fixed).
