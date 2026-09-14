# Spec 123 — The audit ledger: every write records what changed, and an auditor can find it

**Status:** built (RADD-1166 … RADD-1173; `web/scripts/audit-proof.mjs` 14 checks and `history-links-proof.mjs` 10 checks green on the dev instance). **Epic:** RADD-1165. **Depends on:** spec 23 (the event log as history), spec 93 (the kernel registries), RADD-923 (subject refs), RADD-834 (per-actor redaction), spec 121 (public access, whose switches are the first thing this makes audited).

## What is wrong

The `events` table was a sound audit store — append-only, actor-attributed,
indexed by type, actor and entity — and almost nothing written into it said
*what* changed, while the page that read it could not find anything.

Measured on 2026-09-14, before the wave:

- **Two emitters recorded a diff.** `item.updated` (`items/changes.py`, 24
  fields, names resolved at write time) and `project.updated` (name and
  description). The other 85 registered event types wrote a snapshot of the new
  state or a bare name: `role.updated` carried the full permission list after
  the change, `user.updated` new values with no old ones, `field.updated`
  `{key}`, webhooks/releases/cycles/views/labels/teams a name.
- **Settings writes emitted nothing** — nor did public access, SSO providers,
  AI providers, storage hosts and routing rules, Forgejo/GitHub/Jira/Confluence
  connections, mail sources/senders/rules, or time-logging categories. Who made
  a project public, changed SLA hours or flipped an AI toggle left no trace.
- **Kernel auto-wired entities lied.** `kernel/entities.py` declared
  `has_changes=True` on every `<key>.updated` while the generated CRUD router
  computed no diff — automations were promised old/new subjects that never came.
- **48 event types were emitted but never registered** (`role.*`, `user.*`,
  `view.*`, `webhook_endpoint.*`, `automation.*`, `dashboard.*`, `access.*`,
  the SSO/LDAP logins, impersonation…): no label anywhere, no trigger, and
  outside every invariant — found while seeding the first contract test.
- **Search was a table scan.** `GET /audit?q=` cast the whole JSONB payload to
  text and ILIKEd it (121 ms on the 20,615-row dev table). No project column, no
  way to filter by which field changed, and 19,516 of those rows were
  `mail.failed` noise the trail could not exclude.
- **The page showed wire strings.** Action `item.updated`, Entity `item` with no
  name and no link, Details a comma-joined list of field names with no values.
  The per-issue History tab rendered old→new correctly; the audit page reused
  none of it.

## What changes

One kernel primitive and one refusal, then a sweep, then the ledger and the
surfaces on top. Eight issues, one release.

### 1. The change primitive and the refusal (RADD-1166)

`kernel/changes.py` is the one shape a diff takes — the shape items produced
first: `{field, from, to}` for a scalar, `{field, added, removed}` for a
collection, `{field}` alone for a hidden value (a secret, a body), with an
optional `name` for keys a reader would not recognise. `snapshot(obj, fields)`,
`column_fields(row)`, `diff(before, after, *, hidden, collections, labels)`,
`diff_object`, `collection_change`, `hidden_change`, `changed_fields` — pure,
JSON-safe, exported as `radd.sdk.changes` for plugins.

`events.emit(changes=…)` writes the list at the payload's top level. **An event
whose `EventTypeSpec` declares `has_changes` and carries none raises
`ChangesRequired`** — the RADD-923 pattern: a promise the emitter cannot forget
to keep. `[]` is the explicit "nothing visible changed" (the rank-only reorder
says so instead of omitting the key). The auto-CRUD router snapshots before its
setattr loop, so `milestone.updated` finally keeps its promise.

Two burn-down contracts in `tests/test_event_changes.py`, both empty by the
end of the wave: every registered `*.updated`/`*.changed` type declares
`has_changes=True`; every type a module's `*Event` enum can emit is registered.

### 2. The silent admin surfaces emit (RADD-1167)

Each writer the inventory found with no event gained an enum, a registration
and an emit with a diff: `setting.changed` (entity id = the key; a write that
restates the stored value emits nothing; clearing is `to: null`),
`project.public_access_changed` and `page_space.public_access_changed` (the
switch is its own row beside the grant rows underneath — it is what an auditor
looks for), `sso_provider.*`, `ai_provider.*` / `ai_role.changed` /
`ai_preset.*`, `storage_host.*` / `storage_rule.*` (a reorder is one row per
rule that moved; making a host the default is its own row unless folded into
the caller's diff), the four connector families, `mail_source.*` /
`mail_sender.*` / `mail_rule.*`, `work_category.*`,
`project.timelogging_changed`, and a page's labels as a `page.updated` diff.

**Secrets are `hidden` fields**: client secrets, API keys, S3 credentials,
PATs, webhook secrets, mail passwords record that they changed and never a
value, not even a hash. None of these is an automation trigger
(`trigger=False`): a rule that fires on its own configuration being edited is
a loop nobody asked for, and the trigger catalog snapshot stays at 75.

### 3. Every existing `updated` emitter carries a diff (RADD-1168)

What an auditor reads is a name, never an id: a role's permissions as
added/removed and its grants as who-and-where (subject name, project key or
space name — one removed + one added for a role change); a team's members,
managers and owner by name; a field's or link type's scope as project keys; a
cycle's teams; a repo's project; a worklog's category; a page's parent by
title. Content records only that it changed — a comment body, a page body, a
canned response, an automation graph, a form's field list, a card layout, a
widget's configuration. Three writes that emitted nothing gained an event: a
state category edit, resolving a comment, a plugin's contribution switches.
Project-scoped entities name their project as a subject.

### 4. The ledger (RADD-1169)

`events` gains three DERIVED columns (`d123ledger`), filled by `emit` from
what the payload already carries — an emitter declares nothing new:

| column | what | index |
|---|---|---|
| `project_id` | from the subject refs (`payload.project`, `payload.item.project`) or a bare `project_id` | btree |
| `entity_label` | the entity's display label at write time (`RADD-123 Board scroll`, `LG0E7D Ledger`) — outlives the row | — |
| `search_text` | the event's words, the label, the changed fields and their old/new values (4,000 chars) | GIN `gin_trgm_ops`, guarded on `pg_trgm` |

plus a GIN over `payload -> 'changes'` (`jsonb_path_ops`) so "every change to
the assignee field" is a containment probe. Existing rows are backfilled in
SQL from the same keys. On the dev table the text search went from a 121 ms
scan to a 0.12 ms index probe.

`emit` also adds the event's own entity as a subject when a ref is registered
and the emitter did not pass one, so every row about a project, item or page
carries the ref the SPA links from. `EventTypeSpec.audited=False` marks
machine noise — `mail.failed`, `notification.created`, the scheduler tick —
hidden unless asked for.

**Access.** An instance admin reads the instance. Anyone else passes a
`project_id` they hold `project.manage` on and reads only its rows, with item
diffs redacted through the RADD-834 seam the History tab uses (now public as
`items.history.redaction_for`). `GET /audit/catalog` publishes the event and
entity vocabulary from the registry so the SPA hardcodes no list.

### 5. The page (RADD-1170), the links (RADD-1171), the tool (RADD-1172)

Settings → Audit log is a filter bar — project, entity (from the catalog),
person, source, changed field, date range, free text, a system-noise switch —
every filter a typed route search param, so a view is a shareable URL. Each
row is who · what happened (the registry's label) · the entity, linked to its
issue, page or settings screen through one owner (`lib/audit.ts`) · the diff,
folded past three lines. `components/history/ChangeLines.tsx` is the one
change renderer, shared with the issue History tab.

Every settings page carries a footer link, "Change history for this page",
opening the log with that page's entities (and project) preset; entity
editors (field, team, role, automation, webhook, storage host, sign-in
provider) carry a `ChangeHistoryPanel`. `audit_log` over MCP runs the same
service under the same rule (`permission=project.manage`,
`project_param=project_key`).

## Decisions, and what was rejected

- **Structured diffs, rendered at read time** — not a stored sentence per
  event. A sentence cannot be filtered by field, cannot be redacted per actor,
  and cannot be re-rendered when the vocabulary changes.
- **Diffs at write time, from the emitter** — not reconstructed from
  consecutive snapshots at read time. Most payloads are not snapshots.
- **A refusal, not a lint.** `ChangesRequired` at emit is what makes "updated"
  always answer *what*; a test that checks the registry cannot see a forgotten
  kwarg.
- **Names at write time.** The record must stay true after the person, state
  or project it names is renamed or deleted — the items rule since spec 23.
- **Not triggers.** The automation catalog is a parity oracle; forty new
  entries about configuration edits would clutter the builder and change the
  snapshot for no rule anyone writes.
- **Route search params, not the `?s=` seam.** The audit filters are short
  inline params — the readable form that seam itself prefers; a deep link from
  a settings page has to be a plain URL anyone can construct.

## Traps found while building

- **A module's own `changes` local shadows the kernel module.**
  `auth/service.py::update_user_admin` held a dict named `changes`; importing
  `from radd.kernel import changes` beside it is a silent rebind. Every module
  imports it as a module and names its locals `diff`/`patch`.
- **`_role_snapshot` already existed** in `ai/registry.py` — the process-local
  role snapshot. A helper with the same name replaced it and every role call
  raised `'Snapshot' object is not callable`. Grep before naming.
- **A registered-type contract has to compare strings.** `registries.event_types`
  is keyed by `StrEnum` members in some plugins and plain strings in others;
  `set` arithmetic across the two sees `role.updated` twice.
- **`build_catalog` is the builtin half.** A plugin tool is listed by
  `registry_catalog`, and a project-scoped tool is offered only where its atom
  holds — a test with no project sees it hidden even from an admin.
- **The first `input[type=search]` on a settings page is the top bar's.** A
  proof typing into it filters nothing; target the page's own placeholder, and
  drive React's controlled input through the native value setter.
- **Direct `Event(...)` rows have no ledger columns.** A test that inserts
  rows by hand and searches them finds nothing; go through `emit`.
