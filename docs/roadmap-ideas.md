# Radd — product roadmap & build backlog

> **Status:** Tier 1 (items 1–4 → specs 26–29), Tier 2 (items 5–6 →
> specs 30–31, email intake deferred), and the Tier-3 highlights (My Work home,
> CSV export, `/` hotkey → spec 32) are BUILT. Remaining from this doc: the rest
> of Tier 3 (light theme, WIP limits, templates, reactions, j/k nav, item
> DELETE), Tier 4 (AI), and the SSO gate — see `PLAN.md` §8.

Proposed features to take Radd from "technically excellent" to "I'd rather use this
than Jira." Written to be **self-contained** so a fresh session can pick any item and
start building. Grounded in the state at commit `271f036` (audit/history + weblinks/vcs
+ issue-view redesign). Context: solo dev (Hussein) + AI agents; dogfooded in production at a VFX studio for
artist-support intake (a de-facto service desk) and a pipeline dev backlog; GitLab shop;
AGPL, AI-native goal.

## What already exists (don't rebuild)

Auth (local) + RBAC (roles-as-data, field-level grants), projects/items (epic/issue/
subtask, custom fields registry), workflow states, labels, comments (public/internal),
teams, cycles (workspace sprints), releases, dependency links, **SLQ** query language +
autocomplete + swimlanes, saved views, **automations** engine, **reporting** (throughput/
CFD/time-in-state/velocity/burnup), intake **forms**, **time logging + timesheets**,
**webhooks**, Jira importer, **audit/history** (event-log diffs + History tab + admin
audit), **weblinks** + **vcs** link modules, issue side panel + redesigned issue view
(reading column + properties rail + tabbed Activity). React 19 SPA.

## Substrate to reuse (the reason most of this is cheaper than it looks)

- **Event outbox** (`modules/events`): append-only, actor-attributed, `emit()` in-txn,
  `consumer_offsets` cursor, LISTEN/NOTIFY wakeups. `query_events` + `entity_activity`
  read helpers. **This powers notifications, realtime, search indexing, AI indexing** —
  each is "just another consumer" (mirror `webhooks`/`automations` dispatcher).
- **Frontend cache-by-entity** (`web/src/lib/cache.ts`): mutations invalidate by
  `Entity.*`; a realtime message just calls `invalidateEntities()`.
- **Automations engine** (`modules/automations`): SLQ-condition → action rules over the
  stream — reuse for SLA escalation, auto-triage side-effects.
- **Reporting timeline** (`modules/reporting/timeline.py`): reconstructs each item's
  state history from the event log — reuse for SLA timers and aging/WIP reports.
- **vcs connector seam** (`modules/vcs/service.py:upsert_vcs_link`): find-or-create by
  (item, provider, external_id) — the GitLab connector's write target.
- **Module contract** (`radd/module.py`): every feature is a `RaddModule` in
  `RADD_MODULES`; models auto-migrate; see `docs/modules.md` for the map (keep current).

## Recommended build order

Tier 1 compounds (notifications need watchers; realtime makes both instant; search+palette
make it navigable) and all reuse the event spine. **1 → 2 → 3 → 4**, then use-case depth,
then AI, with **SSO** slotted in before any real multi-user rollout.

---

## Tier 1 — decides daily adoption

### 1. Notifications + watchers + Inbox
**Why:** nothing currently tells you an issue was assigned to you, you were @mentioned, or
a comment landed. Biggest single gap; blocks team adoption.
**Build:** `notify` module (outbox consumer, own `consumer_offsets` name). `watchers`
table (auto-watch on assign/comment/create; manual follow). `notifications` table
(recipient, event ref, read/unread). Triggers: @mention, assignment, state change,
comment on watched item, SLA breach (Tier 2). Delivery: in-app center (`GET
/notifications`, mark-read, unread badge) + **email digests** (needs SMTP settings in
`config.py` + a batching consumer). Frontend: bell + dropdown, and fold into the "My Work"
home (Tier 3). @mentions come from the rich editor (item 4) emitting mention tokens, or a
`@[name](user_id)` parse for now.
**Deps:** watchers first; email needs SMTP; @mention polish wants item 4.

### 2. Realtime (WebSocket)
**Why:** live boards/issues without refresh; makes the audit/History feed stream.
**Build:** WS endpoint tailing the outbox (mirror the webhooks dispatcher; per-connection
workspace/permission filter). Client: a WS hook that maps an incoming `{entity, id}` to
`invalidateEntities(qc, Entity.x)` — the cache convention already exists, so surfaces go
live with almost no per-view code. Auth via the session cookie on the WS handshake.
**Deps:** none (substrate ready).

### 3. Search + Cmd-K command palette
**Why:** at 100+ issues/wk you need instant jump-to-key, full-text, people search.
**Build:** `search` module = Postgres FTS index maintained by an outbox consumer (tsvector
column on items or a dedicated index table; index title/description/comments/key). `GET
/search?q=`. Frontend **command palette** (Cmd-K): quick-open issues, run actions (assign,
set state, create), navigate, search — the biggest "feels pro" UI win. pgvector/semantic
search arrives with AI (Tier 4).
**Deps:** none. Palette can ship before FTS (start with key/title prefix search).

### 4. Attachments + rich editor
**Why:** description/comments are plain `<textarea>`. Artist support *needs* pasted
screenshots/frames/logs. Highest-value for TD specifically.
**Build:** **Tiptap** editor (already the planned stack): markdown, @mentions, code blocks,
checklists, image paste. `attachments` module + storage (S3-compatible object store, or
filesystem/Postgres large objects for single-node); attach to items and comments; thumbnails.
Migrate description + comment bodies to rich content (store as JSON or markdown; keep a
plaintext projection for search/SLQ `title ~`).
**Deps:** editor and attachments are separable but best shipped together; @mentions here
feed item 1.

---

## Tier 2 — depth for the two real jobs

### 5. Service desk for TD (SLAs, reporter, queues, canned responses, email intake)
**Why:** TD is a service desk; forms alone aren't enough.
**Build:** a **reporter/requester** field on items (distinct from assignee). **SLA** module:
policies (response/resolution targets, pause in configured states), timers computed from the
event-log state timeline (reuse `reporting/timeline.py`), breach → event → automation +
notification. **Queues** = saved views (already have them) + a queue-oriented list UI.
**Canned responses** (workspace-managed comment snippets). **Email-to-issue** intake
(inbound mail → `items.create_item`, threading replies onto comments). CSAT later.
**Deps:** notifications (1) for breach alerts; automations already there for escalation.

### 6. GitLab connector (make the `vcs` stub real)
**Why:** you're on GitLab; auto-linking MRs/branches/commits + transitioning issues on merge
is the payoff of the vcs module. Highest-ROI connector.
**Build:** the **extensions SDK / connector runner** (planned: out-of-process Python
connectors over the event stream). GitLab connector: consume GitLab webhooks (MR/push/
pipeline) → `vcs.upsert_vcs_link()` on the referenced issue (parse `TD-123` from branch/MR
title/commit), sync MR status, and on merge fire a state transition via `items` service /
automations. Two-way optional (comment sync).
**Deps:** vcs seam ready; needs the connector runtime + GitLab webhook auth.

---

## Tier 3 — UI/UX polish that punches above its weight

- **"My Work" home** — replace the projects-index landing with a personal inbox: assigned
  to me, @mentions, due soon, recently viewed, notifications. (`routes/` new home; reuses
  SLQ `assignee = me`, notifications from item 1.)
- **Keyboard-first nav** — extend the existing `c` hotkey: `j/k` move, `e` edit, `a` assign,
  `x` select, `/` search. Pairs with the palette (item 3).
- **Board WIP limits + column policies**; **issue templates** per type (bug/task bodies,
  tie to forms); **sub-task checklists / acceptance criteria** on an issue.
- **Story points / estimation** field alongside time tracking (velocity is time/count now).
- **Light theme + density toggle** (currently dark-only) — real adoption blocker for some.
- **CSV export** of any saved view; **archive/delete** for items (known gap: no item DELETE).
- **Reactions/emoji** on comments; **due-date reminders / overdue surfacing** (dates exist).

## Tier 4 — the AI differentiator (Radd's distinct angle)

Provider-agnostic LLM client (OpenAI-compatible + native Anthropic; per-user toggles).
Targets the 122-tickets/week pain directly:
- **Auto-triage** incoming TD tickets — categorize, route to team, set priority (an
  automations-style consumer or MCP tool).
- **Duplicate detection** on create + **"similar resolved issues"** to reuse past fixes as
  suggested replies (**pgvector** semantic index as an outbox consumer).
- **Summarize** long issues/threads; **natural-language → SLQ**; standup/status digests.
- **Embedded MCP server** (`/mcp`) generating tools from the field registry — agents act as
  scoped service-account principals. (Already designed for; see PLAN.)

## The adoption gate: SSO (do before real multi-user rollout)

**LDAP/AD + OIDC (PKCE) with group→role sync**, extending `modules/auth`. It's #1 on
PLAN §8 and the prerequisite for a studio actually deploying this. Unglamorous but gating.

---

## Notes for whoever builds these

- Follow the dev rules (`CLAUDE.md`): everything is a module; enums/config over magic
  values; update `docs/modules.md` in the same change; tests only for core invariants;
  ship small runnable slices. Each Tier-1 item is a module + a UI slice — spec it in
  `docs/specs/NN-*.md` first (that's the project convention).
- Tooling: no npm on this box — use `web/node_modules/.bin/{tsc,vite}`; fish has no
  heredocs (use Write/Edit); run the server with `uv run uvicorn --factory
  radd.app:create_app --host 0.0.0.0 --port 8000` (no `--reload`; restart for backend
  changes); `uv run pytest` for the core suite; migrations via `uv run alembic ...`.
