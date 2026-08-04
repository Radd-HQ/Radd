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

## 0. Decisions taken

Answered by Hussein while the audit was being written. Recorded here because the
sections below assume them.

| # | Decision | Consequence |
|---|---|---|
| D1 | **Instance admin bypasses everything; a project manager does not.** `has_manage` stops short-circuiting field and relation checks. | Every refusal becomes explainable by a grant instead of a hardcoded exemption — the precondition for the inspector telling the truth. Some project-manager flows that silently passed will start refusing; that is the point, but it is a behaviour change and needs calling out in release notes. |
| D2 | **Baseline narrows to `item.read@own`.** | ⚠️ **Breaking for every existing deployment** — see the rollout note below. Coupled to D9: `page.read` must leave the Baseline at the same time. |
| D3 | **Project admins assign existing roles on their project; role *definitions* stay global.** | Access management scales off the instance admin without role sprawl. `member.create/update/delete` already exist for this; what is missing is the screen and the delegation check. RADD-826. |
| D4 | **Atom renames auto-rewrite stored roles, token scopes and access grants, emitting an event per change.** | The RADD-701 pattern plus an audit trail. Nothing breaks on upgrade, and a narrowed role is discoverable afterwards rather than invisible. |
| D5 | **Groups become a first-class entity; teams stay flat and can contain groups; groups are grant subjects.** | Supersedes the team-nesting question — the hierarchy lives in the directory, where it already is. Own epic (RADD-827); overhauls the LDAP sync and retires `TeamSource`. |
| D6 | **`@own` means REPORTER**, not creator. | Survives imports (Jira's reporter maps straight across) and makes a form submitted on someone's behalf belong to them. Reporter is reassignable, so ownership can be handed over deliberately. |
| D7 | **Deny: narrower scope wins; at equal scope deny beats allow; instance admin still bypasses.** | One documented back door, kept singular — a deny that could lock out every admin makes an instance unrecoverable without DB surgery. |
| D8 | *(superseded by D5)* | — |
| D9 | **No anonymous reporting.** Email ingest provisions a requester account (`UserSource.EMAIL`) holding only the Baseline. `/public/forms` is removed; **`/public/pages` and `/public/csat` stay.** | One authorisation model instead of two, with the second no longer being the internet-facing one. Forces `page.read` out of the Baseline — otherwise a customer account reads the internal wiki. RADD-828. |
| D10 | **Relations compose with field grants** — `write Priority @assigned` is expressible. | Bigger resolver and a harder grants editor, in exchange for the per-field rules approval workflows actually need. The inspector must explain two qualifiers at once. |
| D11 | **A new resource type defaults CLOSED**; its spec may opt into open. | A plugin author who does not think about access ships something private. The existing six keep their current defaults, so nothing changes today. |
| D12 | **Grant UI: presets AND a sentence builder.** Presets for the common shapes; the advanced mode is a sentence builder, not a control grid. | The fast path stays fast and self-documenting (the inspector can name the preset that produced a grant), while the expert path reads back as the rule it enforces rather than as a row of dropdowns. |
| D13 | **`@team` on an item means `item.team_id`** — the item's own team, nothing inferred. | Narrow and predictable. If "the reporter's team when the item has none" turns out to be wanted, it is a SECOND relation (`@reporter_team`), never a fuzzier definition of this one — a relation whose meaning depends on which columns happen to be set is unexplainable in an inspector. |
| D14 | **Nobody may grant an atom they do not themselves hold.** | One intersection in the grant path, applied to delegated project admins (D3) and to everyone else. Closes the privilege-escalation hole that delegated granting otherwise opens, permanently and without a special case. |

### D5 — Groups become a first-class entity, separate from Teams

Decided while answering the team-nesting question, and it supersedes it. The
current model links an AD group **to** a team (`teams.directory_group_dn` +
`TeamSource`), making that team's membership read-only from the directory. The
decision is to stop doing that:

| | Is | Membership | Nests |
|---|---|---|---|
| **Group** (new) | a directory object, mirrored from AD | from the directory | **yes** — as AD groups do |
| **Team** (existing, changed) | a Radd concept with an owner and a purpose | users **and groups** | no — stays flat |

And: **a group is a grant subject in its own right.** `GrantSubject` becomes
`user | team | role | group`, and `role_grants` gains a `group_id` beside
`user_id`/`team_id`. So "the Render Wranglers AD group may read this space" needs
no team at all.

**Why this is better than team nesting.** It puts the hierarchy where the
hierarchy actually lives. AD already models nested groups and Radd was flattening
that into a link, so a nested AD group's members either arrived as team members
(losing the structure) or did not arrive at all. Teams stop pretending to be
directory objects and go back to being what they are — a Radd-owned grouping with
an owner, managers and a purpose — while groups carry the directory's truth
including its nesting. Two concepts, each with one job, instead of one concept
with a `source` flag deciding which it is today.

**What it touches.** This is not a small change:

- a `groups` table (dn, name, sync state) plus `group_parents` for nesting
- `team_members` becomes polymorphic: a member is a user **or** a group
- `GrantSubject.GROUP`; `role_grants.group_id`; the subject picker everywhere
- the LDAP sync overhauled — it syncs *groups* now, resolving nesting, rather
  than pushing users into linked teams (`groupsync.py`)
- `teams.directory_group_dn` / `directory_group_name` / `TeamSource` /
  `directory_missing_since` all retire
- migration: every directory-linked team becomes an ordinary team containing the
  one group it was linked to — which preserves current behaviour exactly

**The resolution question it creates**, and the reason it belongs in this spec:
a user's effective subjects become *user → groups (transitively) → teams (via
group membership) → roles*. That transitive step is a recursive CTE on every
permission resolution, so it must be resolved once per request and memoised the
way `baseline_permissions` and `readable_projects` already are. Done carelessly
it is a recursive query per check.

**The trap to design around:** AD nesting is often far deeper and wider than
people expect — a user can inherit membership of dozens of groups through two or
three levels. The inspector (RADD-809) must show the *path* ("via Render
Wranglers ← VFX All ← Studio"), because "you have this because of a group you
have never heard of" is otherwise unanswerable.

This needs its own spec; it is filed as its own epic rather than as a child of
the access work, since it changes the identity model rather than the permission
model. Relations (§5.4a) depend on it only for `@team`, which resolves through
whatever the subject graph ends up being.

### D2 rollout — ship the capability, let an admin flip the row

The whole wave ships as **one release** (see the execution brief,
`115-execution-prompt.md`). D2 is the one decision that could break an instance
on upgrade, and it does not have to, because of something RADD-773 already did:
**the Baseline is an editable database row, not a constant.**

So D2 splits into a capability and an act:

| | Ships in the release | |
|---|---|---|
| `item.read@own` is expressible and enforced | ✅ | part of relations (RADD-823) |
| `page.read` removable from the floor without hiding the wiki | ✅ | staff get it from a role granted instance-wide |
| A **pre-flight report** — "narrowing the Baseline would remove access for N users across M projects; here is who and where" | ✅ | new work, RADD-825 |
| The Baseline row's **value** actually changing | ❌ | an admin edits it in Settings → Roles, when their report is clean |

Nothing is held back and nothing breaks on upgrade. The seeded Baseline for a
**fresh** instance becomes `item.read@own`, because a new instance has no one to
break; an **existing** instance keeps whatever its row says until an admin
changes it, having first seen exactly who it would affect.

That is strictly better than a migration that flips it, and it is also the
honest shape: "who may read what" is a policy decision belonging to whoever runs
the instance, not something a version bump should make on their behalf.

`page.read` follows the same rule and for a sharper reason (D9): once email
ingest provisions requester accounts, a permissive page floor is not generous,
it is a leak — an auto-created customer account would read the internal wiki. The
pre-flight report must cover both atoms, and the release notes must say plainly
that leaving `page.read` in the Baseline exposes pages to requester accounts.

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
| 22 | A field **writable everywhere but read-only on TD** | ✅ | One project-scoped grant. Works today — see §3.1; the caveats are #23 and F5 |
| 23 | The same, read-only for **literally everyone** on TD | ❌ | Every grant names a subject, so the minimum expressible restriction is "only X may write here". Needs deny (§5.4) |
| — | *Suggested:* time-bounded / expiring grant | ❌ | No `expires_at` on any grant table |
| — | *Suggested:* deny rule that overrides a grant | ❌ | Every layer is additive; no precedence model |
| — | *Suggested:* read-only **project** (archive) | ⚠️ | Only by editing every role's atoms |
| — | *Suggested:* per-issue-type permissions ("only QA files Bugs") | ❌ | No atom or ACL keys on `type_id` |
| — | *Suggested:* approval-only actor (may transition, nothing else) | ⚠️ | Spec 107 guards check *data*, not *who* |
| 24 | Edit **own** issues, not other people's | ❌ | Needs relations (§5.4a) |
| 25 | Edit **your team's** issues, not those assigned elsewhere | ❌ | Needs relations |
| 26 | A team sees only its own issues — on one project **or** globally | ❌ | Needs relations × scope; the two axes compose (§5.4a) |
| 27 | Edit **own** pages, not others' | ❌ | Needs relations on `pages` |
| 28 | Own vs others on views / dashboards | ⚠️ | `owner_id` exists but is not expressible as an atom qualifier |

**Score: 12 clean, 7 awkward, 10 impossible.** The awkward ones share one cause
(allowlist inversion); the impossible ones share another — **there is no way to
say "the ones that are mine"**. That single missing concept accounts for six of
the ten, across four different resources, which is why §5.4a treats it as a
kernel mechanism rather than an items feature.

### 3.1 Per-project field restriction — it works, and nobody can tell

Scenario 22 deserves its own note because it was raised as a *suspected gap* by
the person who designed the system, and it is not one. The belief was: "fields
are public unless we scope them, but then they become restricted everywhere."

That is **two different mechanisms being read as one**:

| | Controls | Empty means |
|---|---|---|
| **Field scope** — `field_definition_projects` (spec 91) | which projects the field *exists* on | global (exists everywhere) |
| **Field grants** — `access_grants.project_id` (spec 92) | who may read/write it, optionally *per project* | unrestricted (open) |

Scoping a field narrows where it **exists**. Granting on a field narrows who may
**use** it, and a grant carrying `project_id` narrows *only that project* —
because `in_scope` drops it everywhere else:

```python
def in_scope(grant, project_id):
    return grant.project_id is None or grant.project_id == project_id
```

Verified against the pure resolver, one grant (restrict `write` on TD to the
Leads role), no other change:

```
ordinary user   on TD      read=True   write=False    <- read-only, as wanted
ordinary user   on OTHER   read=True   write=True     <- untouched
lead            on TD      read=True   write=True
lead            on OTHER   read=True   write=True
```

So the capability is there and it costs one grant. **The defect is that this is
undiscoverable**: the two mechanisms are adjacent in the same admin surface, both
say "project", and nothing on screen distinguishes "where this field exists" from
"where this restriction applies". If the system's own author reads it the other
way, every admin will. See F12.

Two caveats that are real, and both already have issues:

- **You cannot restrict to nobody** (scenario 23). `access_grants.subject_id` is
  NOT NULL, so a restricting grant always hands the access to whoever it names.
  "Read-only for everyone on TD" has to be faked by granting write to a role
  nobody holds. Deny (§5.4) is the honest form.
- **`project.manage` bypasses it.** `has_manage=True` returns `True` before any
  subject matching runs, so a project manager writes the field regardless.
  Confirmed by probe. That is F5.2, and it is why the bypass should go.

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

### F13 — Half the `manage` atoms do nothing, and one of them misfires
**Severity: medium.** Asked directly — *does `manage` serve any real purpose?* —
the measured answer is mostly no.

Eighteen `*.manage` atoms exist. Counting **direct** enforcement sites (a
`require(...)` naming the atom, excluding the declaration tables):

| Direct uses | Atoms |
|---|---|
| **0** | `canned` `cardpreset` `cycle` `label` `release` `role` `sla` `team` `view` |
| 1–6 | `automation` `form` `webhook` `state` `user` `field` |
| 12–24 | `global` `page` `project` |

**Nine of eighteen are never checked anywhere.** Granting `label.manage` is
exactly equivalent to ticking `label.create` + `label.update` + `label.delete`;
it is a third checkbox whose only meaning is the other three.

**`view.manage` is worse than inert — it is wrong.** The server gates view
writes on `VIEW_CREATE` / `VIEW_UPDATE` / `VIEW_DELETE` (`views/service.py:558`,
`686`, `766`) and never consults `view.manage`. The **client** gates the New-view
affordance on `view.manage` at three sites (`Sidebar.tsx:113,491`,
`ViewModal.tsx:61-62`). Since `manage` implies `create` but not the reverse, a
role granted exactly what the server enforces — `view.create` — gets **no New
View button**, while the API would have accepted the call. Same shape as
RADD-810, different axis: umbrella-vs-granular rather than scope.

**What it was for.** Back-compat, correctly. Spec 36 split per-entity manage out
of `project.manage`/`global.manage`; spec 50 added the CRUD triples and kept
`manage` as an umbrella so pre-existing roles survived with zero backfill. That
was the right call then and is why the atoms exist.

**What it costs now.**

1. **Silent widening.** Adding a CRUD atom to a resource automatically grants it
   to every existing `manage` holder. A permission appears in someone's role that
   nobody granted — the same class of invisibility RADD-773 removed from the
   member floor, still present here.
2. **An explanation burden.** The inspector needs a whole `implied` concept
   (RADD-779) solely to describe grants that were never made.
3. **A vague word attracts jobs.** `project.manage` accreted four unrelated
   responsibilities (F5) precisely because "manage" is loose enough to host them.
4. **92 atoms where ~74 would do**, on a screen already criticised as confusing.

**Recommendation: `manage` becomes a UI affordance, not a stored atom.** Ticking
it ticks the resource's boxes; the role stores granular atoms only. That keeps
the one-click convenience, kills the silent widening, and removes `implied` from
the inspector entirely. The genuinely load-bearing cases are not folded away —
they get real atoms for what they actually authorise (`page.manage` means
*administer a space*, which is not any CRUD triple), rather than hiding behind a
word that means something different on every row.

### F12 — Field *scope* and field *grants* are indistinguishable on screen
**Severity: medium — a capability that exists but reads as missing is worth as
little as one that does not exist.** §3.1 has the detail. Spec 91 gave a custom
field a project scope (where it exists); spec 92 gave it project-scoped grants
(where a restriction applies). Both are edited from the custom-fields admin, both
present a project multiselect, and neither is labelled in a way that says which
question it answers. The observed consequence is that per-project field
restriction — which works, in one grant — was believed to be unbuilt.

The fix is wording and layout, not model: name the two sections for the questions
they answer ("Available on" vs "Restricted on"), and state the default inline —
"no restriction here means everyone who can see the field can write it". The
inspector (F10) should also say *which* project a field restriction came from,
since a grant scoped to one project is otherwise indistinguishable from a global
one in its output.

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

### 5.4a Relations — access qualified by who you are to the record

This is the general form of §5.3, and it should be built as the general form
rather than as an items feature. The brief asks for it across issues, pages,
views, dashboards *and whatever comes next*, which is the definition of a kernel
mechanism.

**The idea in one line:** an atom is qualified by the actor's **relationship to
the record**, not only by the scope it is granted at.

```
item.update            edit any issue                     (today's meaning)
item.update@own        edit issues you reported
item.update@assigned   edit issues assigned to you
item.update@team       edit issues whose team is one of yours
page.write@own         edit pages you authored
view.update@own        edit your own views
```

**Two orthogonal axes**, and keeping them orthogonal is the whole design:

| Axis | Answers | Carried by |
|---|---|---|
| **Scope** (§5.1) | *where* does this apply — instance, project, space | the **grant** |
| **Relation** | *which rows* — any, own, assigned, team | the **atom** |

They compose without interacting. The brief's HR example is
`role[item.read@team, comment.write@team]` granted **on the HR project** for the
project-local version, or granted **instance-wide** for the global version. One
role, two grants, no new vocabulary — which is the test of whether the two axes
were factored correctly.

#### The registry

Each resource contributes its own relations, because only the owning module
knows what "own" means for its rows:

```python
RelationSpec(
    key="team",
    label="on their team",
    #: FILTERING — a SQL expression, for lists/counts/search/aggregates.
    where=lambda actor: Item.team_id.in_(actor.team_ids),
    #: GATING — a predicate over one loaded row, for writes.
    holds=lambda actor, row: row.team_id in actor.team_ids,
)
```

**Both forms are required, and that is the point.** A read restriction must
become a `WHERE` clause or every list, count and aggregate leaks; a write
restriction is asked about one row that is already loaded. Deriving one from the
other is not possible in general, so a relation declares both and a contract test
asserts they agree on a fixture — a relation whose filter and predicate disagree
is a silent leak, and it is exactly the bug this mechanism could introduce.

`items` contributes `own` / `assigned` / `team`; `pages` contributes `own` and
(via the space) `team`; `views` and `dashboards` already have `owner_id`, so
their `own` is a rename of something that exists. A plugin registers relations
for its entity and inherits the whole mechanism.

#### Relations form a lattice

`any ⊃ team ⊃ own`. Holding `item.update@any` implies `@team` and `@own`; the
existing transitive `expand_permissions` closure does this already and needs no
new machinery.

**An unqualified atom means `@any`.** `item.update` today permits editing
anything, so `item.update ≡ item.update@any` and **every existing role keeps
exactly what it had, with no backfill**. That is the RADD-790 precedent: splitting
attachments off `item.update` was a widening rather than a downgrade precisely
because the implication was declared instead of migrated. Same trick, same
reason.

#### "Others" is not a relation

The brief phrases it as *"can edit own, cannot edit others"*. That is the
**absence** of `@any`, not the presence of an `@others` grant — and keeping it
that way is what preserves the additive model. `@others` only becomes meaningful
alongside deny (§5.4), where `deny item.update@others` is a legitimate way to
carve a hole in a broad grant. Define it there, not here.

#### Three traps this must be designed around

1. **Child content must inherit the parent's relation.** If `item.read@team`
   hides an issue, its comments, attachments, worklogs and history must vanish
   with it. Those are separate tables with separate endpoints, and each one that
   forgets is a leak of the exact data the restriction exists to protect. The
   relation belongs on the *item resolution seam* every child already goes
   through — not re-implemented per child.
2. **Every counting surface must inherit the filter.** A restricted user seeing
   "42 issues" on a dashboard and 3 in the list is the classic failure. Reports,
   board column counts, swimlane rollups, search, SLQ and MCP `find_items` all
   inherit it or none do. This is the same "one seam or none" rule that made
   `nearest_epic_case` work in RADD-697.
3. **Relations are computed, spec-92 grants are explicit — keep both.** A view is
   shared by a deliberate act (a grant row); an issue is "mine" structurally (a
   column). Collapsing the two would mean writing a grant row per issue, which
   does not survive 503k items. They answer different questions and both stay.

#### Cost

`@own` is `reporter_id = :me`; `@team` is `team_id IN (:teams)`. Both are indexed
single-column predicates and cost nothing at scale. A relation needing a join
("issues I commented on") is expressible via the spec-97 `item_ids` subquery
seam, and should be marked expensive rather than forbidden.

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

### 5.6a Groups — the subject graph

D5, designed. This ships **in the same release** as the rest of the wave, and it
lands *before* relations, because `@team` resolves through the subject graph and
building that graph twice — once against direct membership, once against groups —
would mean writing the hot path twice and swapping it.

#### The model

| | Is | Membership | Nests | Source |
|---|---|---|---|---|
| **Group** (new) | a directory object, mirrored | from the directory | **yes** | AD only |
| **Team** (changed) | a Radd grouping with an owner and a purpose | users **and groups** | no | local only |

**A group is never local and a team is never directory-mirrored.** That is the
whole point of the split: today `Team` is either, decided by `TeamSource`, which
is one concept doing two jobs. If you want a local grouping, that is a Team; if
you want the directory's truth, that is a Group. Neither grows a flag telling you
which it is today.

`GrantSubject` gains `GROUP` (`user | team | role | group`) and `role_grants`
gains `group_id` beside `user_id`/`team_id`, so a group can be granted access
directly with no team invented to hold it.

#### The subject graph, and why it is the risky part

An actor's subjects become a graph rather than two lists:

```
user ──┬─→ groups ──(nested, transitively)──→ groups
       │        └──(member of)──→ teams
       ├─→ teams (direct membership)
       └─→ roles (via grants to any of the above)
```

Resolution is a **recursive CTE**, and it runs on the hottest path in the
application. It must be resolved **once per request and memoised**, beside
`baseline_permissions` and `readable_projects`, which already exist for exactly
this reason. Done per check it is a recursive query per permission test, and a
list hydrating per-project permissions runs those in a loop.

Two guards the CTE needs on day one, not after an incident:

- **Cycle detection.** AD is a graph, not a tree, and a cycle is rare but legal.
  An unguarded recursive CTE against one does not return.
- **Depth limit.** With a limit, a pathological directory degrades to
  "incomplete"; without one it degrades to "down".

#### What makes this materially different from teams

**Transitive reach is large and invisible.** A user can inherit membership of
dozens of groups through two or three levels, and a grant on a parent group
reaches everyone beneath it. That is the feature — it is why the hierarchy is
worth having — and it is also the thing that will surprise people.

Two consequences that are requirements, not nice-to-haves:

1. **The inspector must show the PATH**, not just the fact: *"via Render
   Wranglers ← VFX All ← Studio"*. "You have this because of a group you have
   never heard of" is otherwise unanswerable, and this change makes that case
   ordinary rather than rare.
2. **The grant UI must show reach before the grant is made**: "this group
   currently resolves to 214 people". Granting to a parent group without seeing
   its size is how an access review finds something nobody intended.

#### Migration preserves behaviour exactly

Every directory-linked team becomes an ordinary team containing the one group it
was linked to. Same people, same access, different shape — and from then on that
team can also hold users directly, or a second group, which it could not before.
`teams.directory_group_dn`, `directory_group_name`, `TeamSource` and
`directory_missing_since` retire; spec 87's AD-linked-team rules (read-only
membership, directory-health chips) move to groups, which is where they always
belonged.

#### Open, and cheap to decide later

A group that **disappears from the directory** keeps its grants and is flagged,
exactly as a missing linked team is today (`directory_missing_since` moves
across). Deleting the grants automatically would make an AD outage into a
permission outage.

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
