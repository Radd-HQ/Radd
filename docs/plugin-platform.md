# Radd Plugin Platform — architecture

**Status:** built — the kernel (spec 93), the frontend platform (spec 94; revised by RADD-1373: core plugins bundled, optional plugins remote), scoped keys (spec 113), the MCP tool registry (spec 114) and the external-plugin workflow ([spec 126](specs/126-external-plugin-workflow.md) and [spec 127](specs/127-managed-plugin-packages.md), which replace the live-install and per-plugin-migration proposals in §5/§10). This document is the reference for turning Radd from a modular monolith into a **kernel + plugins** platform where even builtin features are plugins, third-party developers can ship full featuresets, and everything a plugin exposes — endpoints, events, actions, tables, settings, background workers — plugs into the platform transparently and is governed by the existing RBAC / access framework. `docs/modules.md` is the map of which plugins exist; this document is the machinery; `docs/plugin-ui.md` is the frontend contract; `docs/plugin-development.md` is the how-to.

It turns the "everything is a module" agreement in `CLAUDE.md` into a concrete contract.

---

## 0. The one load-bearing decision: trust & isolation

**Decision: in-process, full-trust plugins. Distribution is external; execution is not sandboxed.**

Plugins are Python packages installed into the server's environment (pip / a plugins directory)
and imported into the running process. They get first-class power: declare SQLAlchemy models,
mount routers, consume the event stream, register background workers, touch the filesystem.

**Why this is forced, not chosen:** the requirements — *register your own DB tables*, *add Celery
workers*, *manage disk packages*, *filesystem management* — are privileged host operations. No
sandbox (subprocess, WASM, RPC-only) can grant them. The moment a plugin needs a table in the
main database or a worker in the main process, it must be in-process and trusted. This is exactly
why Django (apps), Airflow (providers), Home Assistant (custom components), Superset, and Sentry
all use in-process trusted plugins despite being extensible platforms.

**Security posture** (what replaces the sandbox): (a) plugins declare a **capability manifest** of
what they touch (db tables, filesystem paths, network egress, workers, permission atoms) that an
admin reviews before install; (b) **provenance** — signed packages / trusted sources / an allowlist;
(c) **the existing RBAC/access framework governs everything a plugin *exposes* at runtime** (§7),
even though it can't constrain what the plugin's own code does. Untrusted third-party code that
must be isolated stays in the *existing* out-of-process lane (`sdk/` + MCP + `GET /events`), which
we keep as the "arms-length extension" tier. **Two tiers, clearly labelled:**

| Tier | Trust | Can do | Mechanism |
|---|---|---|---|
| **In-process plugin** (this doc) | full | tables, routers, events, workers, disk | Python package + manifest, imported into the process |
| **External extension** (exists) | arms-length | read events, call the API, serve MCP tools | `sdk/` runner over `GET /events` + `POST /api/v1/mcp` |

---

> **A third tier — a sandboxed, untrusted-plugin platform — is a separate, later track** with its own
> design doc. This document is *only* the trusted, admin-installed, in-process tier. Nothing here
> should be compromised to anticipate sandboxing; the two platforms will share vocabulary (the same
> contribution registries) but not a runtime.

## 0.5 The mediation principle — plugins declare intent, the kernel owns mechanics

**A plugin never touches infrastructure directly. It declares *what* it wants through kernel entry
points; the kernel owns *how*.** This is the line between a plugin platform and "code that happens to
share a process," and it is non-negotiable:

- **No raw database access.** A plugin that wants a `milestone` table does **not** import `Base`, open
  a session, or hand-write SQL/Alembic. It **registers an entity** through the kernel's entity entry
  point; the kernel generates the model, owns the migration branch, runs it, and hands back a managed
  repository. The plugin reaches the DB only through the kernel-provided session/unit-of-work — so the
  transactional-outbox invariant (events commit atomically with their mutation) is enforced by the
  kernel, not left to plugin discipline.
- **No home-grown events.** A plugin that wants events **registers its event types with the `events`
  kernel module** and emits via `kernel.events.emit(...)`. It never invents a bus, dispatch, or ad-hoc
  event strings that bypass the registry. Registering an *entity* **auto-registers** its
  `created/updated/deleted` event types — events exist the moment the entity does.
- **No cross-plugin table access.** A plugin reads another plugin's data only through that plugin's
  public service API (dev-rule #1), never its tables.
- **Everything is a kernel-mediated registration** — tables, events, endpoints, permissions, settings,
  tasks, UI. The manifest is a set of *declarations*; the kernel's registries turn them into running
  machinery. A plugin cannot do anything the kernel has no entry point for — and when it needs one that
  doesn't exist, the fix is *add a kernel entry point*, never *let the plugin reach around the kernel*.

The payoff of mediation is **auto-wiring**: because the kernel *owns* an entity's definition, it hands
that entity — for free, no extra plugin code — CRUD endpoints, created/updated/deleted events,
activity-feed entries, search indexing, mention/link support, automation triggers, and RBAC
(CRUD-resource + access `ResourceSpec`) registration. Mediation isn't overhead; it is *how* "add a
milestone → get a first-class feature" becomes a few lines.

**Two authoring layers** (mirrors the frontend decision in §8):
- **Declarative-first** — an `EntitySpec` field/relation DSL covers the common case (standard columns,
  FKs, indexes) and triggers full auto-wiring. This is what "add a milestone entity" should feel like.
- **Code escape hatch** — a plugin needing more (composite constraints, custom types, JSONB query
  shapes) declares a code-defined SQLAlchemy model but still **registers it through the kernel** (model
  registry + kernel-generated migration branch + explicit event-type declarations) and still gets its
  session from the kernel. Power without bypassing mediation.

**Recommendation:** build declarative-first with the code escape hatch as a documented first-class
path — most plugins never need the hatch, and the ones that do (disk manager, storage backends) stay
inside the mediation contract.

## 0.6 Subjects: the kernel owns the shape, the plugin owns the data (RADD-923)

The mediation principle above says a plugin declares intent. Event payloads were the place it was
least true: `emit(payload={...})` took an untyped dict, so every emitter invented its own shape and
fourteen of them did — the issue key was `key` on some events, `item_key` on others, and absent from
nine. RADD-922 unified them by hand and left an AST test to keep them unified, which is a test that
is only necessary because the shape is still hand-built.

**So the emitter passes IDS and the kernel writes the shape.**

```python
await events.emit(
    session,
    event_type=DeployEvent.FINISHED,
    entity_type="deployment", entity_id=deployment.id,
    subjects={"item": item_id, "release": release_id},   # ids — the plugin's half
    payload={"environment": "prod", "duration_s": 214},  # the plugin's own data
)
```

Each entity type registers **one** `EntityRefSpec`, and `payload["item"]` / `payload["release"]`
become canonical refs. You cannot forget to build a ref you never build; eleven emitters stopped
importing `items` just to describe an item. A key collision between a plugin's own data and a subject
ref is a hard error at emit — somebody would otherwise read the wrong thing.

**A declared `EntitySpec` gets all of this free.** `milestones/spec.py` declares five fields; the
kernel generates the ref from them, its CRUD events declare `subjects=("milestone",)`, and the
generated emit passes the id. A project-scoped entity resolves its `project` through the projects
plugin's own ref, so a plugin entity names its project exactly as an item does.

**Declaration is checked at BOOT.** An event naming a subject nothing describes, or an action node
acting on one, refuses to load. The alternative is an automation that saves cleanly, enables cleanly,
and does nothing at 3am — which is the failure this whole seam exists to remove, so the seam must not
reintroduce it.

**`EventTypeSpec.payload_schema` declares only the remainder.** The kernel wrote the refs and
therefore already knows their shape; a schema that repeats them is a second copy that drifts. What is
left is the plugin's own data, and serving it beside the sampled paths is what lets the builder
describe an event that has never fired on this instance. Sampling says what HAS happened; declaration
says what WILL. Validated in dev/test only — a malformed payload must not fail a user's write, because
the event is a side effect of somebody else's action.

### Contributed actions

A plugin could contribute a trigger and a gate but not an ACTION: the executor did
`ActionType(node.type)`, which raises for anything outside the built-in enum, logged "unknown action
type", and dropped the node. So a plugin could say *"when my deployment finishes"* and *"if the AI
thinks it's risky"*, and never *"…then do my thing"*.

`AutomationNodeSpec` gains `subject` and `apply`:

```python
AutomationNodeSpec(
    key="milestone.set_status", kind="action", label="Set milestone status",
    subject="milestone",            # which ids the executor hands it
    permission="milestone.update",  # required to USE the node, checked on WRITE
    arity="item", params_schema=..., plan=plan, apply=apply,
)
```

The plan/apply split is the containment, not a style preference. `plan` runs on every walk including
a dry run, which makes the report free and identical to the real thing. `apply` runs inside the
executor's SAVEPOINT, inside its `RunBudget`, and inside `events.automated()` — so a contributed
action **cannot** spin the engine, **cannot** escape the budget, and **cannot** take the branch down
when it raises. A plugin gets loop safety by doing nothing.

The SPA generates the node's form from `params_schema` (`SchemaForm`) — the promise
`AutomationNodeSpec` already made and nothing kept: a contributed node without a hardcoded editor
used to render an empty inspector.

**North star:** `milestones/automation.py` — the plugin's own event, the kernel's ref, the plugin's
own action on its own entity, with zero edits to `automations`, the kernel or the SPA
(`tests/test_event_subjects.py`, `web/scripts/plugin-contribution-proof.mjs`).

## 1. Kernel vs. plugins

Split the codebase into a **small kernel** and a **fleet of plugins** (builtin plugins live in the
repo; third-party plugins install alongside). Even today's "core" modules become plugins; the
kernel is only the machinery plugins plug into.

**The kernel** — the *generic mechanisms* every feature builds on; never disabled:
- `config` + the **plugin loader / lifecycle manager** (`kernel/loader.py`)
- `db.Base` / session / migration harness **+ the entity & relationship registry** — entity
  registration, cross-plugin foreign keys, entity links (the "entity relationships + DB management")
- the **event outbox + event-type registry** (`events`)
- **access control** — identity, sessions, the **permission-atom registry + RBAC**, the **access grant
  framework**, the **CRUD-resource registry**, and the **acting-user security context + permission-
  aware data SDK** (§7.5); this is *how everything is governed*
- the **settings platform** (scalar cascade) + the **/capabilities aggregator**
- the **contribution registries** (§4) themselves
- the **[primitive] shared seams** (§13): credential vault + OAuth broker, interceptor pipeline,
  egress policy + HTTP client, bot-actor identity, portal/anonymous context, and the **TaskBackend** +
  **StorageBackend** sockets

**Everything else becomes a plugin**, reclassified from today's 45 modules: `slas`, `ldap`, `sso`,
`gitlab`/`forgejo`, `ai`, `mcp`, `docs`, `timelogging`, `dashboards`, `attachments` storage
backends, … down to `items`/`workflow`/`projects` themselves (builtin, always-enabled plugins with
a `core: true` flag so the lifecycle manager won't let you disable the tracker out from under itself).

**Some of today's modules *split* across the line** — the generic mechanism moves into the kernel, the
concrete feature stays a plugin:
- **auth** → kernel keeps identity, sessions, permission atoms, RBAC, access, the security context;
  concrete **login methods** (`local`, `oidc`, `ldap`) become plugins via the auth-method registry.
- **items** → kernel keeps the generic **entity + link/relationship machinery and the SLQ engine**;
  the **issue** itself (epic/issue/subtask hierarchy, issue fields, boards) is the `issues` plugin
  built on `kernel.entities`.
- **settings** → kernel keeps the cascade platform; each plugin owns its own keys + sections.
- **events** → kernel keeps the outbox + type registry; the consumers (notify, search, webhooks…) are
  plugins.
- **fields / views** → kernel keeps the access-grant framework they adopt; custom-fields and
  saved-views are plugins that register into it.

The rule: **generic mechanism other features build on → kernel; concrete feature → plugin, even the
"issue" itself.**

**Success test (the north star):** drop in a `milestones/` plugin — a directory + an install — and it
appears as an automation trigger, a settings page, a capability-gated nav item, a searchable/
mentionable entity, a webhook event, and an RBAC-governed resource, **without editing any other
plugin or the kernel.** The three hardcoded chokepoints that once blocked it are inverted (see Migration history).

> **Searchable / mentionable is real since RADD-1327.** `EntitySpec.searchable` derives a kernel
> `SearchableSpec` (a match on the entity's naming + text fields, filtered through the host's
> row-visibility gate); `mentionable` puts it in the editor's `#` picker, and `EntitySpec.url` is
> where the mention and the audit log link to. Cmd-K reads `GET /search/entities`, which asks every
> registered searchable — issues and pages register theirs through the same seam. A hand-written
> plugin entity registers a `SearchableSpec` directly (`searchables=` on its manifest).

---

## Migration history

The pre-93 codebase, the three chokepoints the kernel inverted (automation triggers → the event registry, provider status → `/capabilities`, hand-written nav → the UI manifest) and the P0–P6 phasing are the migration's history: spec 93 is its definition of done, spec 94 the frontend half, and `BUILD-LOG.md` the log.

---

## 4. The extension-point catalog (the heart of the platform)

The plugin contract is `RaddPlugin`:
a **manifest of contributions**. Each field is aggregated by the loader into a kernel **registry**;
the kernel iterates registries without knowing any plugin's identity. Everything below is
`register_*`-style (the `access.registry` pattern), declared on the manifest or via import-time
registration guarded by `depends_on`.

```python
@dataclass(frozen=True)
class RaddPlugin:
    # identity & lifecycle
    id: str                       # stable, e.g. "radd.slas" or "acme.disk-manager"
    version: str                  # semver of the plugin
    api_version: str              # radd SDK version it targets (§9)
    core: bool = False            # builtin, non-disableable
    depends_on: tuple[str, ...] = ()
    capabilities_required: CapabilityManifest = ...   # db/fs/net/workers it will use (admin-reviewed)

    # --- contributions (each → a kernel registry) ---
    entities:        tuple[EntitySpec, ...] = ()      # models + CRUD-event/activity/search wiring
    migrations:      MigrationSource | None = None    # per-plugin Alembic branch (§5)
    routers:         tuple[APIRouter, ...] = ()
    event_types:     tuple[EventTypeSpec, ...] = ()   # register CUSTOM events with the events kernel module; entity CRUD events auto-registered from `entities`
    consumers:       tuple[ConsumerSpec, ...] = ()    # offset-tracked stream consumers
    automation_actions:    tuple[ActionSpec, ...] = ()
    automation_conditions: tuple[ConditionSpec, ...] = ()
    tasks:           tuple[TaskSpec, ...] = ()         # background/scheduled work (§6)
    config_schema:   type[BaseSettings] | None = None  # the plugin's OWN env-vars (§ Settings)
    settings_keys:   tuple[SettingSpec, ...] = ()      # scalar cascade keys it owns
    settings_sections: tuple[SettingsSectionSpec, ...] = ()  # its admin pages (backend descriptor)
    permissions:     tuple[PermissionSpec, ...] = ()   # RBAC atoms it defines (§7)
    crud_resources:  tuple[CrudResourceSpec, ...] = () # spec-50 CRUD resources (§7)
    access_resources: tuple[ResourceSpec, ...] = ()    # spec-92 grantable resources (§7)
    capabilities:    tuple[CapabilitySpec, ...] = ()   # what /capabilities reports (§8)
    integrations:    tuple[IntegrationSpec, ...] = ()  # socket providers (§4a)
    ui:              PluginUiManifest | None = None     # nav/routes/pages/widgets (§8)
    on_startup / on_shutdown / exception_handlers / openapi_augmentors  # kept from today
```

> **As built (RADD-1328).** The sketch above is the design; these are the fields that exist on
> `RaddPlugin` today for the parts a plugin most often reaches for:
>
> | Sketch | Built |
> |---|---|
> | `consumers: ConsumerSpec` | `consumer_names` (+ `consumer_descriptions`, and `consumer_resume` — `ConsumerResume.CURSOR`/`HEAD`, where each continues when the plugin is re-enabled, RADD-1372) + the SDK's consumer API: `read_events`, `get_offset`/`set_offset`/`offset_exists`, `run_consumer` (the head-seeded, at-most-once runner the core delivery consumers use) — `tests/test_sdk_consumer.py` runs one on `radd.sdk` alone |
> | `automation_actions`, `automation_conditions` | `automation_nodes: AutomationNodeSpec` — every node kind (source/filter/gate/action/verdict); the built-in nodes are registered the same way (RADD-1322) |
> | `triggers` | `trigger_kinds: TriggerKindSpec` (a button, a clock, a validation, or anything event-backed a plugin defines — RADD-1323); event triggers are every `EventTypeSpec` with `trigger=True` |
> | — | `token_providers` (`{{root.field}}` vocabularies), `automation_templates` (whole automations offered as disabled drafts) |
> | — | `notification_kinds: NotificationKindSpec` — inbox + preferences matrix rows, and the events that produce them (RADD-1326) |
> | `entities` search wiring | `EntitySpec.searchable/mentionable/url` derive a `SearchableSpec`; `searchables=` for hand-written entities (RADD-1327) |
> | — | `record_local_entities` — entity types the realtime hub may narrow to one item's refresh |

Consumer callbacks passed to `run_consumer` inherit the source event's automation
cause during both planning and delivery. Delivery may receive several consecutive
batches when causes differ. The cursor still commits before delivery: failures
are not retried by this runner. Hand-written consumers that emit derived events
should wrap their work in `with radd.sdk.derived_from(event):`; historical
bootstrap can additionally pass `silent=True`.

Contributed automation nodes should render action text through `ctx.render`.
Missing named outputs refuse the action and appear as a skipped plan; optional
event fields keep their existing rendering behavior. Submitter-facing verdicts
use the separate original-draft renderer, whose message token allowlist is
`item.title`. Findings published about replacement search results retain their
severity but get generic wording before being relayed to the submitter.

Dynamic nodes can declare `shape_params=("answers",)` (for example) to name only
the parameters their `ports_for` and `outputs_for` callbacks read. The editor
sends those parameters to the shape endpoint, debounces shape changes, and keeps
the last valid shape while loading. Omit `shape_params` when all parameters matter.

Registries the kernel exposes (one per contribution kind): `entities`, `events`(produce),
`consumers`, `triggers`, `actions`, `conditions`, `tasks`, `settings`, `permissions`,
`crud_resources`, `access_resources`, `capabilities`, `integrations`, `ui`. Each is a dict populated
at load and read by exactly one generic consumer. No consumer names a plugin.

### 4a. Integration points (typed plugin-to-plugin sockets)

Some plugins don't add *nouns* — they add *implementations* of an interface another plugin consumes.
These are named "sockets": a plugin declares it *provides* or *consumes* a socket.

- **StorageBackend** (built, spec 102) — one blob client per storage-host type (`filesystem`, `s3`);
  a plugin host type is one more provider.
- **AIProvider**, **VcsProvider** — already interfaces; formalize as sockets.
- **TaskBackend** — the Celery ask (§6): a plugin *provides* a queue backend the kernel *consumes*.
- **NonWorkingDaysProvider** (built, RADD-1031) — calendar dates nobody works; `leave` provides, the
  SLA clock consumes, every provider's answer UNIONs.
- **PersonAvailabilityProvider** (built, RADD-1387) — which PEOPLE are away on a date
  (`away_user_ids(session, day, user_ids)`); `leave` provides, round-robin assignment consumes,
  answers UNION, and with no provider nobody is away. The per-person sibling of NonWorkingDays —
  one answers for the instance, this one for a person, and neither stands in for the other.
- **RoutingRule** (built, spec 102) — one storage routing-rule type; `attachments` provides
  `user_choice`/`cidr`, `ai` provides `llm` (RADD-1387), and an optional `captured_types` lets a
  type say which uploads it decides ahead of "ask the uploader". A stored rule whose type has no
  live provider is skipped.
- **TransitionCheckProvider** (built, RADD-1383) — one workflow transition-rule `check` a plugin
  serves (`validate` on write, `prepare` + pure `failure` at evaluation, `moved` after a state
  change). `approvals` provides `require_approval`. A stored rule whose provider is gone FAILS
  CLOSED: disabling a plugin must never silently open a gate an admin configured.
- **SearchDocumentSource** (built, RADD-1384) — the non-item documents search shows beside issues
  (`search` = reader-gated FTS ranking, `resolve` = the readable subset of candidate ids).
  `pages` provides; search's deflection and Ask mode consume. No provider = no documents.
- **SemanticCandidateSource** (built, RADD-1384) — meaning-ranked `(id, distance)` candidates per
  entity type. `ai` provides from its embeddings; search fuses them by RRF, time-budgeted, and
  falls back to full-text only on any failure — or when no provider is loaded.
- **NotificationSubjectProvider** (built, RADD-1385) — a non-item thing notifications are about,
  keyed by entity type: where it lives (`locate` → notify's `SubjectRef`), who watches it, who may
  read it (the one gate for fan-out and the mail re-check), and its container's subscription
  picker and labels. `pages` provides `page`. A withdrawn provider notifies nobody and its queued
  rows stop being mailed.
- **NotificationAudienceSource** (built, RADD-1385) — more people participating in an issue than
  its watchers; every source UNIONs. `participants` provides the current members of an item's
  participant teams.
- **MailTransport** (built, RADD-1385) — carries notify's `NotificationMail` (its kind and failure
  vocabulary are notify's). `mailintake` provides it. None registered ⇒ email is unavailable and
  recorded as such; the inbox is untouched.

Sockets are just a small typed registry: `register_provider(socket, name, impl)` +
`get_provider(socket, name)` + a settings key that picks the active provider. This is how "add S3 as
a plugin" and "add Celery as a plugin" become uniform.

---

## 5. Plugin-owned tables & migrations

As built (spec 126, "Validation and limits"): declarative entities get their initial tables created; existing tables are never evolved automatically, so a schema-changing plugin ships an explicit migration run at deployment. The per-plugin Alembic-branch design this section used to hold was not built (Decision 2 below records it as intent).

---

## 6. Background work & the Celery ask

Today: `radd/worker.py` `PeriodicLoop` + `RADD_RUN_WORKERS`, poll-based, in-process. The ask is
"add Celery workers to handle automations" *as a plugin*.

**Decision: abstract task dispatch behind a `TaskBackend` socket (§4a); `PeriodicLoop` becomes the
default builtin backend; a Celery plugin provides an alternative.**

- Define `TaskSpec` (a unit of periodic background work) and a `TaskBackend`
  interface (`schedule(periodic)`; as built, the backend keeps no roster and
  `kernel.runtime.PluginRuntime` starts/stops each plugin's loops with the plugin, RADD-1372). Consumers (automations, notify,
  search, SLA timers) **register `TaskSpec`s** instead of hand-rolling loops.
- The kernel ships the **`localloop` backend** (today's `PeriodicLoop`, unchanged behavior). A
  `celery` plugin registers a `TaskBackend` provider; selecting it routes all `TaskSpec`s through
  Celery. Automations "handled by Celery workers" = install the plugin, set the backend.
- **Why:** it makes the queue itself pluggable (the exact "swap the engine" ask) without every
  consumer knowing which backend runs. **Alternative rejected:** hardcode Celery — breaks the
  zero-dependency default deploy and violates "I don't want these builtin."

---

## 7. RBAC / access as the plugin control plane

Your requirement: "plugin actions, endpoints and events should be registered with and controlled by
the RBAC / CRUD / access framework." Three registries, two of which are **static today and must
become plugin-contributable**:

1. **Permission atoms** — today an enum. Convert to a **registry**: a plugin declares
   `PermissionSpec(key, label, scope)`; the atom appears in role editors automatically. A plugin's
   router guards its endpoints with its own atoms; roles grant them; global grants (spec 87) work
   unchanged.
2. **CRUD resources** (spec 50, `auth/types.py` `CRUD_RESOURCES`) — today a **hardcoded tuple**.
   Convert to `register_crud_resource(...)` so a plugin's entity gets create/read/update/delete
   permission surfaces + the generic CRUD UI without editing auth.
3. **Access grants** (spec 92, `access.registry`) — **already** dynamic. A plugin registers a
   `ResourceSpec` and gets `/grants` + `<AccessGrantsEditor>` for free.

Net: **everything a plugin exposes is governed by the framework that already governs custom fields
and views** — a plugin cannot introduce an ungoverned endpoint/resource because registering it *is*
how it becomes reachable and grantable. (This governs what the plugin *exposes to users*; it does not
constrain the plugin's own code — see §0 trust posture.)

---

## 7.5 Permission-aware by default — the acting-user context & the data SDK

§7 covers how a plugin *registers* what it governs; this covers how the kernel *enforces* the acting
user's permissions on everything the plugin *does at runtime* — so a plugin handling issues respects
the user's permission scheme **without writing a single permission check.**

**The security context.** Every request the kernel routes carries an **acting user**. The kernel's
data services take that context and enforce it — row visibility (project membership, archive/delete
state) **and** field-level read grants (spec 92). Because plugins reach data *only* through these
services (mediation, §0.5/§5), permission enforcement is not something a plugin opts into — it is the
only path available.

- **On-behalf-of-user is the default.** `kernel.items.query(slq, as_user=ctx.user)` returns exactly
  the issues that user may see, hydrated with only the fields they may read. A dashboard plugin
  *cannot* leak an issue or a field the viewer lacks access to, because the SLQ/hydration service
  applies the same grants the REST API applies.
- **System access is an explicit, audited escalation.** A plugin that must act beyond a user (a sync
  job, a periodic recompute) calls `kernel.as_system(reason=...)`, which is (a) gated by a
  `system_access` entry in the plugin's capability manifest (admin-reviewed at install, §0) and
  (b) logged. Least-privilege by default; god-mode is opt-in and visible.
- **Plugin endpoints are guarded natively.** A plugin router declares the permission atom an endpoint
  needs (`@requires("milestone.update")`); the kernel enforces it *and* injects the acting-user
  context, which flows into every `kernel.*` call the handler makes. So an endpoint is both
  RBAC-guarded (atom) and permission-scoped (data) with no plugin-authored auth code.

**The data SDK (the "easy access to SLQ / issue info" ask).** The kernel exposes its core read/query
services as first-class, permission-aware SDK functions — a headline of `radd.sdk` (§9), not an
afterthought:

- `kernel.items.query(slq: str, as_user)` — the **SLQ engine**, returning permission-scoped, hydrated
  items. A dashboard widget is a one-liner.
- `kernel.items.get(id, as_user)` / `.list(filter, as_user)` / `.history(id, as_user)`.
- `kernel.projects`, `kernel.users`, `kernel.comments`, `kernel.fields`, … — stable public service
  functions, all acting-user-scoped.
- Writes go through the same context: `kernel.items.update(id, patch, as_user)` runs the same
  permission + workflow-guard checks the REST endpoint would, and emits the same events.

> **As built.** The data SDK is `radd.sdk`'s lazily resolved service functions (`get_item`,
> `list_items`, `create_item`, `update_item`, …, each taking the acting `User`), not a `kernel.items`
> namespace. `kernel.as_system` and the `system_access` manifest entry were not built.

**Why it's safe *and* easy:** the plugin gets a rich, high-level API (SLQ, issue CRUD, comments) with
near-zero code, and is structurally incapable of bypassing the user's permissions — the property that
makes mediation valuable, extended to reads and authorization. A dashboard, a report, an automation
action, and a service-desk plugin all consume the same permission-scoped SDK.

## 8. The frontend — the genuinely hard half

### Bundled core plugins, remote optional plugins (RADD-1373)

**Decided 2026-09-26.** Every plugin's UI lives in its own module (`<module>/ui/src`) and contributes
through the same `definePlugin` API — slots, query/data/command sources, `activate`. What differs is
how it reaches the browser:

- **Core plugins are bundled.** A core (`core=True`, non-disableable) plugin's `ui/package.json`
  says `"radd": {"bundled": true}` and exports its entry (`"."`). `web/scripts/plugin-packages.mjs`
  (run by `prepare-federation`) generates `web/src/plugins/static.generated.ts`; the host imports
  those entries at build time and `plugin-loader.syncStaticPlugins()` registers them BEFORE the
  first render. The manifest declares no `remote`, so `/capabilities` lists no remote for it. It is
  still gated: when `/capabilities` `plugins` omits it (a module left out of `RADD_MODULES`) it is
  withdrawn, and it returns when the plugin does.
- **Optional plugins are remotes.** They build to `ui/dist/remoteEntry.js`, and the loader imports
  and activates one when it is enabled and withdraws it on disable, live. A bundled plugin's name in
  `remotes` is ignored.

Why: a core plugin can never be withdrawn at runtime, so shipping it as a remote bought nothing and
cost a network round trip before any picker could render. It showed as "Selection unavailable ·
<uuid>" on every page load, plus a per-mount query identity that refetched shared catalogs on every
mount. The invariants are tested: `test_frontend_federation.py` (bundled == core, no remote on a
bundled manifest); `plugin-boundaries.test.mjs` (no `web/src` import of plugin source by relative
path, the generated list in sync); `plugin-loader.test.mjs` (boot registration, withdrawal and
return without duplicates, a same-named remote ignored).

**The wiki is bundled too (RADD-1392).** Pages became core, and its whole UI moved into `pages/ui/src`: the host router mounts the package's route exports (`@radd-plugin-ui/pages/index-page|space-page|print-page`, lazily) at the addresses the package declares (`PageRoute`), settings and the sidebar section arrive through slots, and the editor, comment kit and access editors it shares with the host come through the SDK host bridge (`docs/plugin-ui.md`). A core package may export implementation the host imports (queries, links); a cross-PLUGIN import stays contract-only.

**Public contracts.** The host and other packages import a plugin's types and contracts only through
its package `exports` (`@radd-plugin-ui/<plugin>/<file>`), never by relative source path.

**Loading and caching.** While any remote is loading, `setRemotesLoading(true)` lets an empty `Slot`
render its `pending` prop (default nothing) instead of its "unavailable" `fallback`. Contributed
queries are ordinary shared TanStack queries, keyed by owner plus arguments with normal stale
times, and paging keeps the previous page. The loader removes a withdrawn plugin's cached queries
(`["plugin-query", name, …]` and `[name, …]`), so a re-enable reads fresh. Writes are plain
`useMutation`s and are never aborted.


### Shared singletons, and the editor runtime on demand (RADD-1397)

A remote externalizes the shared modules and keeps their bare specifiers; the host's import map
resolves each to a `/shared/<slug>.js` shim that re-exports the host's instance. ONE list,
`web/scripts/shared-modules.mjs`, names them, and `plugin-boundaries.test.mjs` holds the import map
(`web/index.html`), the remote build's externals (`packages/plugin-sdk/vite.mjs`), the host's
publisher (`web/src/shared-runtime.ts`) and the generated shims to it.

- **Eager:** React, React DOM, the router, the query client and the SDK — published on
  `globalThis.__RADD_SHARED__` at boot.
- **Lazy — the editor runtime:** `prosemirror-model`, `prosemirror-state`, `prosemirror-view`. The
  host's editor engine is a chunk that loads when an editor first mounts, so the host registers
  LOADERS on `globalThis.__RADD_SHARED_LAZY__` (through the very paths its editor imports them by)
  and the shims top-level-await them. A plugin that extends the editor with ProseMirror plugins — an
  editor binding — gets the editor's own instances; a bundled copy would not work (keys,
  `instanceof`, node classes). Importing one costs nothing until an editor exists.

Only what CROSSES into host code is shared. Co-editing moved into the collab remote on this rule
(RADD-1397, contract in `docs/plugin-ui.md`): its binding is y-prosemirror over the shared
ProseMirror, while yjs, y-protocols and y-websocket are the remote's own — nothing in the host ever
touches a Y.Doc, so there is no second copy to disagree with. Milkdown is not shared: it is the host
editor's wrapper, and a binding needs only ProseMirror. The host keeps a feature-neutral mechanism —
`RichEditor`'s `binding` and the `liveDocuments` contribution — and `web/src` names no co-editing
code at all (boundary test).

Remote builds externalize the shared modules through Rolldown's `esmExternalRequirePlugin`
(`packages/plugin-sdk/vite.mjs`) and substitute `process.env.NODE_ENV`, so bundled CommonJS
dependencies consume the host's React without Node globals in the browser. That plugin alone owns the
external list: a duplicate top-level `external` rule bypasses the conversion, and only loading the
built bundle in a browser shows it — a type-check passes.

The contracts plugins contribute through — option directories, pickers, field controls, query and command sources, schedules, change lines, transition-rule editors, VCS connector tabs — are in `docs/plugin-ui.md`. The per-issue record of moving each surface out of the host (RADD-1343) is `research/plugin-isolation/README.md`.

---

## 9. The public SDK & API versioning

External plugins compile against a **public surface** that must be stable. Today there's no line
between "public API" and "internals" — plugins reach into `service.py` functions freely.

**Decision: carve out `radd.sdk` — the *only* imports a plugin may use — and semver it.**
- `radd.sdk` re-exports: the registry `register_*` functions, the base specs/dataclasses,
  `events.emit`/read, the settings/access/permission APIs, `Base`/session helpers, the socket
  interfaces, and the **permission-aware data SDK (`kernel.items.query`/SLQ, item & comment CRUD,
  projects, users) — all acting-user-scoped (§7.5)**. Everything else in `radd.*` is internal and may
  change any release (`radd/sdk.py`).
- A plugin declares `api_version`; the loader refuses to load a plugin whose `api_version` is
  incompatible with the running kernel (semver major). This is what lets the app upgrade without
  silently breaking installed plugins.
- **Cost:** discipline — every cross-plugin call already goes through `service.py` (a dev rule), so
  this is mostly *labelling* which of those are public, plus a compat gate in the loader.

---

## 10. Lifecycle & the plugin manager *(shipped — `modules/pluginmgr/`)*

The kernel gains a **plugin manager** (service + admin UI) with a real lifecycle, replacing "edit
`RADD_MODULES` and restart":

```
DISCOVERED → INSTALLED (migrations up) → ENABLED (active) ⇄ DISABLED → UNINSTALLED (migrations down)
```

- **Discovery:** Python entry points (`radd.plugins`) + a plugins directory + builtin plugins.
- **Install:** validate `api_version` + capability manifest (admin review) + `depends_on`, run the
  plugin's migration branch up, register it. **Uninstall:** reverse, with an explicit data-destroy
  confirm (uninstall keeps data by default; a separate "purge" drops tables).
- **Enable/disable (runtime, no restart):** flip an `active` flag. On enable: mount routers, start
  its `TaskSpec`s/consumers, expose its nav/permissions. On disable: unmount, stop loops, hide UI —
  tables and data remain (it's still *installed*). This is the WordPress activate/deactivate model
  and the honest reading of "runtime toggle in the admin UI."
  - *Feasibility note:* runtime router mount/unmount and loop start/stop are achievable (FastAPI
    router list is mutable at runtime with care; loops already gate on a flag). Migrations are **not**
    done at enable time — only at install — which is what makes runtime enable/disable safe.
- **Failure isolation:** a plugin loop crashing already can't kill the process (loops swallow +
  log). Extend that: a plugin whose `on_startup`/router import throws is quarantined (marked
  `errored`, its contributions rolled back) rather than aborting boot — one bad plugin must not take
  down the app.
- **State:** an `installed_plugins` kernel table (id, version, state, config) is the source of truth;
  `RADD_MODULES` config becomes the *builtin* set + a bootstrap allowlist, not the full list.

---

## 13. Derived extension points (from the ecosystem stress-test)

We stress-tested this design against ten candidate community plugins (catalogued in
`docs/plugin-ideas.md`). **None are scheduled** — the goal is only that the kernel be *shaped* so any
of them could be built and plugged in seamlessly later. The exercise surfaced nine extension points to
account for. Each is tagged **[primitive]** (foundational plumbing many plugins share — design into the
platform build) or **[seam]** (design the interface now, implement when the first consuming plugin is
actually built). Nothing here is built ahead of a real need; this section exists so we don't have to
retrofit the *shape* later.

| Extension point | Tag | Why / which ideas need it | Phase |
|---|---|---|---|
| **Secrets/credential vault + OAuth broker** — encrypted, scoped per-plugin/user/instance; redirect handling | primitive | most integrations are dead without it (Slack, GitHub, Calendar, SMTP) | P5 |
| **Pipeline / interceptor registry** — synchronous, ordered, can transform or *veto* an in-flight operation | primitive | a new shape beyond post-commit events + in-txn hooks (upload filter, pre-save validation) | P1 |
| **Egress policy in the capability manifest + kernel HTTP client** — declared outbound hosts, audited, retried/rate-limited | primitive | every outbound integration (Slack, AI, GitHub, exporters) | P3/P5 |
| **Plugin/bot actor identity** — attributable write-backs that compose with the acting-user/system model (§7.5) | primitive | AI triage, sync write-backs | P1 |
| **Anonymous/portal security context + public-route registration** — a non-user principal, routes off `/api/v1`, rate-limited | primitive | portals, status pages, a metrics endpoint, public forms | P2/P4 |
| **Field-type registry** — pluginnable field *types*: validator + storage + widget + optional recompute (ties to spec-52 render widgets) | seam | formula/geo/currency fields | P4 |
| **Auth-method registry + privileged provisioning API** — register login methods; create/deactivate/merge users & teams under system-access | seam | SCIM/SAML | later |
| **Bulk-ingest + external-ID mapping helper** — idempotent upsert keyed to an external system (generalizes the Jira importer) | seam | GitHub sync, importers | later |
| **Task scheduling extensions** — cron semantics + per-user/per-tenant fan-out | seam | calendar sync, nightly reports | P5 |

Two confirmations from the exercise: **frontend federation (spec 94) is mandatory, not optional** (ideas
2/3/5 need real UI), and **the sandboxed tier (§0) earns its separate existence** (no-code admin
scripting is untrusted logic that must not run in-process).

## 14. Plugin packaging & per-plugin dependencies

Plugins bring their *own* code dependencies — Python and frontend — and the platform must resolve and
load them. This is part of what "install a plugin" means (§10).

**Python.** Each plugin is a Python distribution with its own `pyproject.toml` declaring its deps.
- Builtin plugins are wired as **optional-dependency extras** of the server package (`radd[ai,ldap,
  slas,…]`), so enabling a builtin pulls exactly its deps — the default install stays lean.
- External plugins are `uv`/`pip`-installed; the lifecycle **install** step runs dependency resolution
  and records the locked set, then runs the plugin's Alembic branch, then registers its contributions.
- **One shared interpreter** (in-process tier) ⇒ a single resolved graph. Two plugins requiring
  *incompatible* versions of the same library is unsatisfiable — install **detects and refuses** it
  with a clear error (a concrete reason the *sandbox* tier, §0, exists). Plugins should pin the widest
  compatible ranges. Heavyweight/native deps are surfaced in the capability manifest for admin review.

**Frontend (React/JS).** An optional plugin's UI is a **module-federation remote**; a core plugin's is
bundled into the host (§8, RADD-1373).
- The plugin ships its own built bundle that may include its own npm packages (charts, editors, …);
  the **host provides shared singletons** — React, React-DOM, the router, the query client, the
  design-system, and (loaded on demand) the ProseMirror editor runtime — so there is exactly one
  React instance, one theme and one editor engine (§8, RADD-1397).
- Plugin UIs live in the plugin dir with their own `package.json`. Core ones are bundled at app-build
  time; optional ones, builtin or external, serve their own `remoteEntry.js` + assets, loaded at runtime
  per the UI manifest. The host federation config pins the shared-singleton versions.
- Version skew is gated like the Python `api_version` (§9): a plugin built against an incompatible host
  UI SDK is refused rather than loaded.

**Net:** `install` = resolve Python deps → migrate (plugin Alembic branch) → build/register the
frontend remote → register contributions; `uninstall` reverses. Dependency-resolution failures and
version conflicts are install-time errors, never runtime surprises.

## Decisions made on your behalf (veto any)

1. **In-process, full-trust plugins** (§0) — forced by table/Celery/disk requirements; sandboxing is
   impossible for those. Untrusted code stays in the existing out-of-process SDK/MCP lane.
2. **Per-plugin Alembic migration branches** (§5), not schema-per-plugin (would kill cross-plugin FKs)
   and not `create_all` (can't evolve schemas).
3. **Install/uninstall (migrations) split from enable/disable (runtime flag)** (§10) — the only way
   runtime toggling is safe with plugin-owned tables.
4. **Frontend = declarative manifest first (covers ~80%), module federation for bespoke UI** (spec 94; RADD-1373 later bundled core plugins).
5. **`TaskBackend` socket with `localloop` default + optional `celery` plugin** (§6), Celery not builtin.
6. **A public `radd.sdk` + semver `api_version` gate** (§9) — the price of stable external plugins.
7. **Reclassify existing modules as builtin `core` plugins**; no rewrite, additive manifest fields (Migration history).
8. **Mediation is mandatory (§0.5)** — plugins declare intent through kernel entry points; the kernel
   owns DB schema/migrations/sessions and the event-type registry. No raw DB access, no home-grown
   event bus, no cross-plugin table reads. Auto-wiring is the payoff.
9. **A sandboxed untrusted-plugin platform is a separate later track** (§0), not part of this design.
10. **Permission-aware by default (§7.5)** — the kernel carries an acting-user context; every data-SDK
    call (SLQ, item CRUD) enforces the user's row + field-level permissions. System/god access is an
    explicit, capability-gated, audited escalation. Plugins write no auth code.
11. **Kernel = generic mechanisms, plugins = concrete features** (§1) — access control, entity &
    relationship/DB management, the event registry, the settings platform, the security context + data
    SDK, and the [primitive] seams are kernel; every feature (down to the *issue* itself) is a plugin.
    Some current modules split across the line (auth, items, settings, events, fields/views).
12. **Per-plugin dependencies** (§14) — plugins ship their own Python (pyproject/extras) and JS
    (module-federation remote + shared singletons) deps; install resolves them; incompatible
    shared-library versions are refused in the in-process tier.
