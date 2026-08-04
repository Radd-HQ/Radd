# Spec 115 — access control: audit, gaps, and a target model

**Status:** audit + proposal. No code changed. Written to be picked up later.
**Scope:** the whole access system — permission atoms, roles, grant scoping, the
spec-92 resource ACL framework, plugin contribution, and the permission inspector.

The brief was: *full control — global, project, component and field level*, a
list of concrete scenarios that must be expressible, dynamic plugin
registration, an inspector on both Users and Teams showing where every grant
comes from, and an end to the confusion where an atom must be held at **global**
scope even when the intent was to limit it to one project.

This document answers all five. Section 3 is the scenario matrix (what works
today, what does not); section 4 is the defect list with evidence; section 5 is
the proposed target model.

---

## 1. What exists today

Access is decided by **three independent layers**. They are not alternatives —
a single request can pass through all three — and most of the confusion in the
brief comes from the boundaries between them being invisible.

### Layer 1 — atoms and roles (`modules/auth/authz.py`)

- A **permission atom** is a string, `resource.action` (`item.read`,
  `state.create`). 92 exist on the live instance.
- A **role** is a DB row holding a list of atoms. Four are builtin
  (`baseline`, `admin`, `member`, `viewer`); the rest are user-defined.
- **Baseline** is the floor every active user holds without being granted
  anything. It is an editable row (RADD-773), seeded `item.read` + `page.read`.
- **Umbrella expansion** (`IMPLIED_PERMISSIONS`, applied transitively):
  `project.manage` → `state.manage` → `state.create/update/delete`.
- **Instance admin** (`users.instance_role == "admin"`) short-circuits
  everything and holds `all_permission_keys()`.

### Layer 2 — grant scoping

Who holds a role, and *where*:

| Mechanism | Table | Scope |
|---|---|---|
| Direct project membership | `project_members` | one project |
| Team attached to a project | `project_teams` | one project |
| Role grant | `role_grants` | instance-wide, **or** one project, **or** one space |

`effective_permissions(user, project=…)` unions all four sources plus the
baseline. `effective_permissions(user, space_id=…)` unions space-scoped grants
plus the baseline. `effective_permissions(user)` — neither — unions only
instance-wide grants plus the baseline.

### Layer 3 — resource ACLs (spec 92, `modules/access/`)

A per-record ACL: `access_grants(subject_type, subject_id, access,
resource_type, resource_id, project_id)`. Subjects are **user | team | role**.
Six resource types are registered:

| Resource | Accesses | Default | Model |
|---|---|---|---|
| custom field | read, write | **open** | flags |
| builtin field | read, write | **open** | flags |
| view | viewer, editor, owner | closed | hierarchical |
| dashboard | viewer, editor, owner | closed | hierarchical |
| attachment | read | **open** | flags |
| page space | read, write | **open** | flags |

Two models: **flag** (an access is open until some grant restricts it, then only
matching subjects pass) and **hierarchical** (highest matching level wins,
nothing = no access).

---

## 2. The core defect: scope is a property of the atom, not the grant

`PERMISSION_SCOPES` assigns each atom **exactly one** `PermissionScope`
(`project` | `global` | `instance` | `space`). This single fact is the source of
the confusion named in the brief, and of at least five shipped bugs.

What the scope actually controls is **which catalog group the atom renders in**
and **which check signature is expected**. It does *not* control where a grant
applies — a role granted instance-wide contributes its project-scoped atoms to
every project's resolution (`_granted_role_ids` unions global grants in).

So the model is already many-to-many in behaviour while being one-to-one in
declaration. The consequences:

1. **`require(ITEM_READ)` with no project asks a structurally different
   question** than `require(ITEM_READ, project=X)`. Roughly 28 endpoints used
   the former as a stand-in for "is this a member", which could not fail while
   `item.read` was in a hardcoded floor — and became a hard 403 for real members
   the moment RADD-773 made the floor editable. The fix was two new seams,
   `require_anywhere` and `readable_projects`, which exist *only* to paper over
   this.
2. **The roles matrix tells an admin a half-truth.** It groups atoms under
   "Project permissions" and "Global permissions" as though an atom belonged to
   one. An admin who wants `item.read` limited to one project sees it filed
   under Project and reasonably concludes a project grant is enough — which is
   correct for the item list but *not* for the ~28 cross-project surfaces.
3. **A client cannot ask the right question without knowing the atom's scope.**
   `perms.global()` vs `perms.project()` vs `perms.anyProject()` — three client
   seams whose correct choice depends on a server-side table the client does not
   have. RADD-808 and RADD-810 are 11 sites that chose wrong.
4. **Adding a scope silently breaks the UI.** RADD-791 added `space`; the SPA's
   scope list did not, so four `page.*` atoms rendered nowhere and were
   ungrantable for the entire life of the feature (RADD-808).

**This is the item to fix first.** Everything in section 4 is downstream of it.

---

## 3. Scenario matrix

The brief's scenarios, plus ones the audit suggests. **Verdict** is what the
system can express *today*.

| # | Scenario | Verdict | How / what is missing |
|---|---|---|---|
| 1 | Super admin bypassing all checks | ✅ | `instance_role == admin`; short-circuits in `effective_permissions` |
| 2 | Admin over all issues on **one project** | ✅ | Grant `Admin` role scoped to that project |
| 3 | Admin over all pages in **one space** | ✅ | Grant a role with `page.*` scoped to that space (RADD-791) |
| 4 | Users assignable to issues | ✅ | Assignability is member-floor, not an atom |
| 5 | Create issues + comment, **cannot modify the issue** except replying / setting state | ⚠️ | Possible but **inverted**: builtin-field grants are allowlists, so you must add a restricting grant on *every* field you want locked and then grant it back to everyone else. There is no "this role cannot write field X" |
| 6 | Create issues + comment, **cannot modify state** | ⚠️ | Same shape. `state` **is** a grantable builtin field (`_BUILTIN_FIELD_MAP`), so this works — but only by restricting `state` globally and granting it back |
| 7 | Read pages in a space + comment, **cannot create or edit** | ✅ | `page.read` + `comment.write` scoped to the space |
| 8 | Edit/create/comment in **one space** | ✅ | `page.write` scoped to that space |
| 9 | Edit/create/comment in **all spaces** | ✅ | Same role granted instance-wide |
| 10 | View issues on **one project** | ✅ | `Viewer` scoped to that project |
| 11 | View only issues **they or their team created**, + comment + attach | ❌ | **No row-level item access exists.** `item.read` is all-or-nothing per project. `items` registers no spec-92 resource. This is the single largest gap |
| 12 | Create an issue but **cannot edit specific fields** | ⚠️ | As #5 — allowlist inversion |
| 13 | **Read** specific fields but not modify | ✅ | Custom + builtin field grants, `read`/`write` flags, `write` implies `read` |
| 14 | Read **and** edit specific fields | ✅ | Same |
| 15 | View only attachments **visible to their team** | ✅ | Attachment ACL, `read` access, team subject (spec 102) |
| 16 | Read internal comments | ✅ | `comment.read_internal` |
| 17 | Read **only** internal comments shared with their team | ✅ | `Comment.visible_to_teams` + the atom |
| 18 | View read-only boards | ✅ | View share level `viewer` |
| 19 | View **and edit issues in** a board | ⚠️ | Two unrelated systems: board access is a view share, issue editing is `item.update` on the project. A board grant confers nothing on issues, which is correct but not discoverable |
| 20 | Create own views, **not** modify issues | ✅ | `view.create` without `item.update` |
| 21 | Create own views, modify issues, **and share** | ✅ | `view.create` + `item.update`; sharing is view `owner` |
| — | *Suggested:* time-bounded / expiring grant | ❌ | No `expires_at` on any grant table |
| — | *Suggested:* deny rule that overrides a grant | ❌ | Every layer is additive; no precedence model |
| — | *Suggested:* read-only **project** (archive) | ⚠️ | Only by editing every role's atoms |
| — | *Suggested:* per-issue-type permissions ("only QA files Bugs") | ❌ | No atom or ACL keys on `type_id` |
| — | *Suggested:* approval-only actor (may transition, nothing else) | ⚠️ | Spec 107 guards check *data*, not *who* |

**Score: 11 clean, 6 awkward, 5 impossible.** The awkward ones share one cause
(allowlist inversion); the impossible ones share another (no row-level model).

---

## 4. Findings

### F1 — Atom scope is single-valued (section 2)
**Severity: high.** Root cause of RADD-808, RADD-810, RADD-672, RADD-674,
RADD-788, RADD-774. Fix in the target model.

### F2 — No row-level access for items
**Severity: high.** `item.read` is project-wide. Scenario 11 is inexpressible,
and it is the most commonly requested shape in a service-desk deployment
("customers see their own tickets"). `items` registers no spec-92 resource, and
the framework as written keys grants to a `resource_id` — workable for a
handful of records, not for a per-issue ACL at 500k rows. This needs a
**predicate** model (owner / reporter / team) rather than per-row grant rows.

### F3 — Field grants are allowlists, not denylists
**Severity: medium.** `has_access` returns `spec.default_open` when no grant
restricts the access; once *any* grant restricts it, only matching subjects
pass. So "everyone except contractors can edit Priority" is one grant, but
"contractors cannot edit Priority" requires restricting Priority and re-granting
it to every other subject. Admins think in the second form. There is no deny
precedence anywhere in the system.

### F4 — The same verb means opposite things
**Severity: medium, and actively misleading.** From `types.py`:

```
COMMENT_DELETE    = "comment.delete"     # delete others' comments (author deletes own)
WORKLOG_DELETE    = "worklog.delete"     # delete others' worklogs (author deletes own)
ATTACHMENT_DELETE = "attachment.delete"  # delete your OWN attachments
```

`comment.delete` and `worklog.delete` mean *other people's*. `attachment.delete`
means *your own*. Identical grammar, inverted meaning, no way to tell from the
roles matrix — the description column is the only signal and an admin reading
three checkboxes in a row will not notice.

### F5 — `manage` has at least four distinct meanings
**Severity: medium.** `project.manage` is simultaneously:
1. an umbrella expanding to `state.manage`/`release.manage`/`field.manage`;
2. the `has_manage` **bypass** in every field-grant check
   (`SubjectContext.has_manage`) — a back door around Layer 3;
3. the gate for hard-delete atoms (`item.delete`, `comment.delete`, …);
4. the "historical write" gate letting an importer set an inactive assignee.

Meanwhile `page.manage` implies only `page.delete`, and `view.manage` coexists
with an entirely separate owner/editor grant system for the same objects.
"Manage" is not one concept.

### F6 — `CrudAction.READ` is declared and never used
**Severity: low, but it is the reason scenario 10-style asks feel awkward.**
`CRUD_RESOURCES` has no resource listing `READ`; the comment says reads "stay
open to members" by design. That is a defensible default and an undeliverable
one: there is no way to grant read of *cycles* or *labels* to one role without
granting it to everyone.

### F7 — Plugins cannot contribute a resource ACL
**Severity: high for the plugin brief.** The kernel has 15 contribution
registries (`entities`, `permissions`, `crud_resources`, `slq_fields`,
`view_types`, `mcp_tools`, `page_extensions`, …). **There is no registry for
spec-92 access resources.** All six adopters call
`access.registry.register_resource(...)` directly, which means a plugin wanting
per-record grants for its own entity must `import radd.modules.access` —
violating dev rule 1 (modules talk through public seams and declared extension
points) and the plugin contract in `docs/plugin-platform.md`.

So: a plugin **can** contribute atoms and CRUD triples that Team/User/Role
grants manage. It **cannot** contribute a resource whose individual records are
grantable. That is exactly half of the brief's requirement.

### F8 — `PermissionSpec.scope` omits `space`
**Severity: low.** `kernel/specs.py:111` documents `"project" | "global" |
"instance"`. RADD-791 added `space`. A plugin author reading the contract cannot
discover the fourth scope. Same drift class as RADD-808, one layer up.

### F9 — Uninstalling a plugin leaves dangling atoms in stored roles
**Severity: medium.** Roles store atom **strings**. RADD-701 needed a migration
to rewrite stored roles when `doc.*` became `page.*`, precisely because a stale
atom in a role's JSONB breaks `GET /roles` (`RoleRead.permissions` is typed).
Plugin uninstall has no equivalent step, so removing a plugin can leave roles
referencing atoms the catalog no longer knows.

### F10 — The inspector explains only Layer 1
**Severity: medium.** `permission_sources` (RADD-779) walks the baseline and
granted roles. It does not read `access_grants`, so it cannot answer "why can
this person see this space / view / field" — the questions Layer 3 decides. It
also has no Team view, no backlinks, and its `?project_id=` parameter has no UI.

### F11 — No expiry, no audit trail on grants
**Severity: low-medium.** No `expires_at` on `role_grants` or `access_grants`;
temporary elevation must be remembered and revoked by hand. Grant changes emit
events, but there is no "who granted this, when" column on the row itself, which
is the first thing asked in an access review.

---

## 5. Proposed target model

### 5.1 Scope becomes a property of the grant

Replace the single `PERMISSION_SCOPES[atom] -> Scope` with:

```python
@dataclass(frozen=True)
class AtomSpec:
    key: str
    resource: str
    action: str
    #: Scope kinds this atom can be CHECKED at. Most are {PROJECT}; a few are
    #: {INSTANCE}; page atoms are {SPACE}; some are legitimately both.
    checkable_at: frozenset[ScopeKind]
    #: Human sentence for the matrix, in the imperative.
    description: str
```

and a single **scope containment ladder**:

```
instance  ⊃  global  ⊃  {project | space}  ⊃  resource
```

A grant is `(subject, role, scope_kind, scope_id | None)`. A check is
`holds(subject, atom, at=scope)`, satisfied by a grant at that scope **or any
scope that contains it**. This is already the de-facto behaviour of
`_granted_role_ids`; making it explicit means:

- `require_anywhere` and `readable_projects` collapse into
  `holds(atom, at=ANY_PROJECT)` — one seam, not three.
- The client asks `can(atom, scope)` with the scope it is rendering in, and the
  server's ladder decides. `perms.global` / `perms.project` / `perms.anyProject`
  become one function, which removes the RADD-810 class permanently.
- The roles matrix groups by **resource**, not by scope, and shows the scopes
  each atom *can* be granted at. An admin who wants `item.read` on one project
  picks the project scope on the grant, not a different atom.

**Migration:** `PERMISSION_SCOPES` becomes `checkable_at` with each current
value as a single-member set — behaviour-identical on day one. Widening
individual atoms is then a reviewable one-line change per atom, not a
rewrite. Stored roles are untouched (they hold atoms, not scopes);
`role_grants` already carries `project_id`/`space_id` and gains
`scope_kind` as a generated/derived column.

### 5.2 Verbs get one meaning each

| Verb | Means | Notes |
|---|---|---|
| `read` | see it exists and its values | **newly grantable** for config resources (F6) |
| `create` | bring a new one into being | |
| `update` | change an existing one | |
| `delete` | destroy **anyone's** | uniform (fixes F4) |
| `manage` | all four **plus** configure the resource itself | no bypass semantics |

and ownership becomes a **modifier**, not a different verb:

```
comment.delete        # anyone's
comment.delete.own    # your own
attachment.delete.own # what attachment.delete means TODAY
```

`attachment.delete` is renamed to `attachment.delete.own`, and a new
`attachment.delete` gets the uniform meaning. This is a breaking atom rename and
takes the RADD-701 treatment: a migration rewriting stored roles, token scopes
and access grants, guarded on each table existing.

Separately, **`has_manage` stops being a bypass** (F5.2). A project manager
should hold the field atoms explicitly through the Admin role rather than
skipping Layer 3, so that the inspector can *explain* the access instead of
reporting a hardcoded exemption.

### 5.3 Row-level access by predicate, not by row

For F2, do **not** write an `access_grant` per issue. Extend the resource spec
with an optional **visibility predicate** contributed by the owning module:

```python
ResourceSpec(
    resource_type="item",
    row_predicates={
        "own":  lambda actor: Item.reporter_id == actor.id,
        "team": lambda actor: Item.team_id.in_(actor.team_ids),
        "assigned": lambda actor: Item.assignee_id == actor.id,
    },
)
```

A role then carries `item.read` **qualified** by a predicate
(`item.read@own`, `item.read@team`), and the predicate compiles into the SLQ
`WHERE` the listing already builds — so it costs one extra clause, not a join
against a grants table at 500k rows. Scenario 11 becomes a role, and the same
mechanism serves "only issues assigned to me" and any predicate a plugin
registers.

### 5.4 Deny precedence

Add an explicit `effect` (`allow` | `deny`) to `access_grants`, with **deny
winning** at equal or narrower scope. That makes F3's natural phrasing
expressible without inverting the whole model, and it is opt-in: no existing row
carries `deny`, so behaviour is unchanged until one is written.

### 5.5 Plugin parity (F7, F8, F9)

- Add `access_resources: dict[str, AccessResourceSpec]` to the kernel registry,
  mirroring `access.registry.ResourceSpec` the way `CrudResourceSpec` mirrors
  `auth.types.ResourceSpec`. `modules/access` reads the kernel registry;
  plugins stop importing it. Unmount removes the type with its plugin.
- `PermissionSpec.scope` becomes `checkable_at`, documented with all four kinds.
- Plugin uninstall runs a **role sweep**: atoms belonging to the departing
  plugin are stripped from stored roles, token scopes and access grants, the
  RADD-701 migration pattern applied at runtime. Without it, uninstalling
  breaks `GET /roles`.
- A contract test (the `test_permission_scope_contract.py` pattern from
  RADD-808) asserts every kernel-declared scope is one the SPA renders.

### 5.6 The inspector

One endpoint shape, two subjects:

```
GET /users/{id}/access[?scope=project:<id>|space:<id>]
GET /teams/{id}/access[?scope=…]
```

returning **three sections**, each row carrying its provenance *and a link to
the thing that granted it*:

1. **Atoms** — as today, plus the scope each is held at, and `implied_by` naming
   the umbrella when the atom was not granted directly.
2. **Resource access** — per registered resource type: which records, which
   access level, and whether it is held by grant or by `default_open`
   ("readable because nothing restricts it" is a different fact from "granted",
   and today they look identical).
3. **Effective answers** — a short list of plain-language conclusions
   ("can edit issues in 3 projects", "cannot transition FOO-* to Done"),
   because the first two sections are still evidence rather than an answer.

Every row gets a **backlink**: role → `/settings/roles#<id>`, team →
`/settings/teams/<id>`, project grant → the project's access screen, space grant
→ Settings → Pages, baseline → the Baseline role. The instance-admin case stays
one sentence, as RADD-779 decided.

For teams, the same view answers "what does membership of this team confer",
which is the question a team owner actually has and which nothing answers today.

---

## 6. Suggested sequence

Each step is independently shippable and leaves the system working.

| # | Work | Why this order |
|---|---|---|
| 1 | **Inspector: resource grants + Team view + backlinks** (5.6) | Pure addition, no model change. Makes every later step verifiable — you can *see* what a change did |
| 2 | **`checkable_at` + scope ladder** (5.1) | Behaviour-identical migration; collapses three client seams into one and kills the RADD-810 class |
| 3 | **Matrix regrouped by resource**, scope chosen on the grant | The UI half of 2 — this is what removes the confusion in the brief |
| 4 | **Read atoms for config resources** (F6) | Small, unblocks the viewer-shaped scenarios |
| 5 | **Verb normalisation + `.own` modifier** (5.2) | Breaking rename; needs 1 to verify and a RADD-701-style migration |
| 6 | **Deny precedence** (5.4) | Opt-in, additive |
| 7 | **Row-level predicates** (5.3) | Largest; unblocks scenario 11 and the service-desk shape |
| 8 | **Plugin parity + uninstall sweep** (5.5) | Depends on 2 and 5 having settled the vocabulary |
| 9 | **Grant expiry + granted-by** (F11) | Independent; do whenever |

Steps 1–4 remove most of the reported pain. Steps 5–8 are the structural work.

---

## Appendix — how the audit was run

- Atom catalog and scopes read from `modules/auth/types.py` and cross-checked
  against the live instance: **92 atoms — 50 global, 38 project, 4 space**.
- Enforcement seams traced through `modules/auth/authz.py`
  (`effective_permissions`, `require`, `require_anywhere`, `readable_projects`,
  `permissions_for_projects`, `permission_sources`).
- Resource ACL model read from `modules/access/{registry,resolution,service}.py`;
  adopters found with `grep -rn 'register_resource('` — six.
- Field-level enforcement confirmed **server-side** at
  `modules/items/service/visibility.py:86` (`_check_builtin_field_rules`), with
  the grantable builtin list at `_BUILTIN_FIELD_MAP` (15 fields, `state`
  included).
- Client scope mismatches found mechanically: every `perms.global(Permission.X)`
  in `web/src` cross-referenced against X's server scope — **21 correct, 10
  mismatched** (filed as RADD-810).
- Plugin contribution surface read from `kernel/registry.py` (15 registries) and
  `kernel/specs.py` (`PermissionSpec`, `CrudResourceSpec`).
