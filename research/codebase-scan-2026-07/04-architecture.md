# Architecture — boundary findings

Measured against the two rules that define the layering:

> **Dev rule 1** — modules talk to each other only through public `service.py`
> functions, emitted events, and declared extension points. Spine exception:
> `auth.models.User` and `projects.models.Project`.
>
> **Kernel = mechanism only** — plugins own policy and UI.

---

## A1 — The kernel imports six things from modules

`kernel/entities.py` reaches into `radd.modules` at six sites:

```python
# kernel/entities.py:171
from radd.modules.auth.deps import CurrentUser
# :178, :225
from radd.modules.auth import authz
# :181, :233
from radd.modules.projects import service as projects_service
# :190
from radd.modules.events import service as events
```

They are deferred (function-local) imports, so there is no import cycle at
startup — but the dependency is real and it points the wrong way. `EntitySpec`
auto-wires a table + CRUD + events + RBAC, and to do that it must know how auth,
projects and events work. The kernel is therefore not mechanism-only; it encodes
the policy that a plugin entity is project-scoped and permission-checked the way
core modules are.

**This is arguably correct and should be a documented decision rather than an
accident.** The alternative — the kernel declaring *sockets* that auth/projects/
events fill at startup — is more code for a benefit nobody has asked for. But
the current shape means a Radd kernel cannot be lifted out of Radd, which the
plugin-platform framing implies it can. Worth one paragraph in
`docs/plugin-platform.md` either way.

**Severity: low, but it is the highest-level inversion in the tree.**

---

## A2 — The spine is bigger than CLAUDE.md says — **CORRECTED (RADD-885): resolved, and enforced**

RADD-885 implemented what this section recommended and went further than
either option below: CLAUDE.md dev rule 1 now names the measured six-module
de-facto spine (`auth` User, `projects`, `items` WorkItem, `workflow` State,
`teams`, `fields` FieldDefinition) as importable for READS — writes still go
through the owner's service — and `server/tests/test_module_contracts.py`
enforces it: every other module's `models.py` is off-limits (the audit's
residue, e.g. the `events.models.Event` readers, is frozen in the test's
burn-down allowlist), and every cross-module import must be DECLARED
(`depends_on` / `weak_depends`), with undeclared edges refused. The rule is
no longer narrated; it fails a test. The measurement that motivated the
change stays below as history.

CLAUDE.md documented two spine tables at scan time and said *"of the ~130
cross-module model imports that exist, 82 are these two."* Measured then,
excluding `auth.models.User` and `projects.models.Project`:

**69 cross-module model imports remain.** They are not evenly spread — two
tables account for most:

| Imported | By | Sites |
|---|---|---|
| `events.models.Event` | realtime, webhooks, notify, search, attachments, automations, reporting, items, googlechat, mailintake, csat, ai | **13** |
| `items.models.WorkItem` | automations, timelogging, slas, csat, views, releases, forms, canned, search, participants, jiraimport, workflow, linktypes | **14** |
| `fields.models.FieldDefinition` | items (10), automations (2), ai (2), views (1) | **15** |
| `workflow.models.State` | items (6), forms (1) | **7** |
| others (`access`, `teams`, `cycles`, `releases`, `itemtypes`, `labels`, `comments`, `attachments`, `timelogging`, `pages`) | — | 20 |

Sample sites:

```
modules/realtime/hub.py:15          from radd.modules.events.models import Event
modules/webhooks/service.py:17      from radd.modules.events.models import Event
modules/slas/service.py:19          from radd.modules.items.models import WorkItem
modules/items/filters.py:20         from radd.modules.fields.models import FieldDefinition
```

**The finding is not "69 violations".** It is that `Event`, `WorkItem` and
`FieldDefinition` are **de-facto spine tables** and the rule does not say so. A
rule with 69 unacknowledged exceptions is not being enforced; it is being
narrated. Two honest options:

1. **Widen the documented spine** to `User`, `Project`, `Event`, `WorkItem`,
   `FieldDefinition` — accepting that these five are the shared vocabulary — and
   hold the line hard on everything else (which would leave ~20 real cases).
2. **Give the three a read seam** (`events.service.rows_for(...)`,
   `items.service.get_item`, `fields.service.definitions_for_project` — the last
   already exists) and migrate the callers.

Option 1 is a paragraph; option 2 is a wave. Option 1 is almost certainly right
for `Event` (an append-only log is a legitimate shared read) and questionable
for `WorkItem` (a table 14 modules can join against is a table nobody can
change).

**Severity: medium at scan time; resolved by RADD-885** — the constraint now
does the work its documentation claims, mechanically.

---

## A3 — `access.registry` is a private registry doing a kernel's job

```python
modules/fields/service.py:12   from radd.modules.access.registry import ResourceSpec, register_resource
modules/views/service.py:147   register_resource(_VIEW_SPEC)
modules/attachments/acl.py:61  access_registry.register_resource(_SPEC)
modules/dashboards/service.py:302
modules/pages/page_access.py:76
```

Five modules import another module's `registry` submodule to register
themselves. The kernel has **fifteen** contribution registries (`entities`,
`permissions`, `crud_resources`, `capabilities`, `slq_fields`, `view_types`,
`widget_types`, `mcp_tools`, `page_extensions`, `tasks`, `consumers`,
`integrations`, …) and none of them is for access resources — so this one
extension point sits in a module instead of the kernel, and a plugin wanting
per-record grants must import `radd.modules.access` directly.

`kernel/registry.py:3` even says *"This is the `access.registry` pattern,
generalized"* — the kernel was modelled on this registry and then did not absorb
it.

**Already filed as RADD-818.** Repeated here because it is the clearest
kernel/module misplacement in the tree, and the scan found it independently.

**Severity: medium.**

---

## A4 — Two modules reach into another module's non-public internals

Beyond models, a handful of imports reach into genuinely internal files:

```python
modules/items/history.py:85     from radd.modules.comments.visibility import internal_comment_visible
modules/items/bulk.py:29        from radd.modules.workflow.guards import TransitionError
modules/items/rollup.py:19      from radd.modules.auth.authz import Permission
modules/items/slq/*.py          from radd.modules.items.slq import <lexer/parser helpers>
```

- `comments.visibility` — a visibility predicate is exactly the kind of thing
  that should be a `service.py` export; it is imported for a correct reason
  (history must filter internal comments) through the wrong door.
- `workflow.guards.TransitionError` — an exception type; belongs in
  `workflow.types` with the rest of the vocabulary.
- `auth.authz.Permission` (37 sites) — **deliberate**, and the code says so:
  `authz.py:46` carries `# noqa: F401 — re-exported: every module imports
  Permission from here`. Not a violation; it is an undeclared public seam. Move
  it to `auth.types` (where it is defined) or document `authz` as public.
- `items.slq` internals — CLAUDE.md already flags this: *"The lexer, parser and
  coercion helpers are generic query machinery… They belong in the kernel
  eventually; don't copy them."* Known, unfiled.

**Severity: low.** Each is a one-line move; the value is that the rule stops
having quiet exceptions.
