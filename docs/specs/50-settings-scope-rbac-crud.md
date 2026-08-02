# Spec 50 — Settings scope redesign + RBAC CRUD verbs + per-team internal comments

**Status: SHIPPED.** All seven slices below are built, migrated, and
verified (565-test suite green, frontend builds, endpoints exercised end-to-end).
As-built deltas from the draft are called out in "Known simplifications / deferred".
The design problem: *scope is not a first-class dimension.* Settings live in one flat `/settings` area (19 tabs shown
to everyone, gated only per-page); per-project config is reached from that global
area behind a project `<select>` rather than from inside the project; and the
workspace→project cascade is **additive** (a `project_id IS NULL` row applies to
all projects, project rows add on top) — there is no **override-with-fallback**
resolution anywhere. This spec makes scope first-class across settings IA and the
authz model, and closes three specific RBAC gaps.

Decisions taken (interview): **full CRUD verbs on every resource** ·
**builtin/system fields become read-restrictable** (not just write) · **per-team
internal comments where teams _narrow_ the `comment.read_internal` audience**.
Assumed unchanged: **single workspace** (no switcher — workspace stays the
org-wide default layer above projects, per PLAN §9's global-unique-key decision);
union/highest-wins permission resolution (already correct in `combine_permissions`).

Already shipped, NOT rebuilt here: highest-wins union, teams↔many-projects
(`project_teams`), per-project role grants (`project_members` + `project_teams`),
custom-field read/write grants to roles-or-teams.

---

## 1. Permission model → full CRUD verbs (one authz seam unchanged)

Today the `Permission` enum (`auth/types.py:22-56`) is a mix: items have
`read/create/update` (**no delete** — delete/archive rides `item.update`/
`project.manage`), docs have `read/write/manage`, everything else is a single
coarse `*.manage`. Normalize to **`{resource}.{create,read,update,delete}` for
every resource**, resolved through the existing union seam.

- **Content resources** get true, independently-grantable CRUD incl. the missing
  deletes: `item`, `comment`, `doc`, `worklog`, `attachment` →
  `.create/.read/.update/.delete`. This adds the first-class **`item.delete`**,
  **`comment.delete`**, **`doc.delete`**, **`worklog.delete`**, `attachment.delete`.
- **Config/admin resources** likewise get CRUD atoms: `state`, `field`, `label`,
  `role`, `team`, `member` (project access), `automation`, `form`, `sla`,
  `release`, `cycle`, `webhook`, `canned`, `view`, `import`, plus scope roots
  `workspace`, `project`, `instance`.
- **Backward compatibility via the existing umbrella mechanism** (`IMPLIED_PERMISSIONS`
  + `expand_permissions`, `auth/types.py:130-146`): keep `*.manage`,
  `project.manage`, `workspace.manage` as **umbrellas that expand to their CRUD
  atoms** in the pure decision core. Every stored role row (`Role.permissions`
  JSONB) keeps working with zero data migration at check time; a migration then
  mirrors the grown builtin definitions into the immutable builtin role rows
  (same contract as spec 36's `43c250fb2a01`). Granular atoms do NOT imply the
  umbrella.
- `PERMISSION_SCOPES` gains an `INSTANCE` member of `PermissionScope` (today only
  `PROJECT`/`WORKSPACE`) so instance-scoped settings (§2) have a home; each new
  atom is scoped. `GET /permissions` catalog + the roles matrix render the CRUD
  columns grouped by resource.

**Known simplification (honest):** some CRUD cells are degenerate — a `webhook`
has no representation to `read` distinct from managing it; `label.read` is "see
labels," which every item-reader already has. Rather than mint dead permissions,
degenerate cells are **defined but aliased** to the resource's meaningful verb in
the enforcement map, so the matrix is complete without check-time no-ops. The
roles-matrix UI hides aliased cells behind a "advanced" toggle to avoid noise.

## 2. Scope becomes first-class: three settings surfaces, nav gated by scope perms

Replace the single flat `/settings` with three permission-gated shells. **Each
shell's nav is filtered by the viewer's effective permissions at that scope** —
you see a tab only if you can manage the thing behind it (fixing "19 dead tabs").

| Surface | Route | Gate | Tabs |
|---|---|---|---|
| **Instance** | `/settings/instance/*` | `instance_role == admin` | Auth/SSO/LDAP · SMTP · Storage · AI provider · Connectors · Work-week & scalar **instance defaults** · MFA policy · Audit |
| **Workspace** | `/settings/*` (relabeled "Workspace") | workspace perms | Roles · Teams · Members · Labels · Cycles · Automations · Canned · Doc spaces · Workspace-wide Fields/Field-rules · Workspace **defaults** for cascaded scalars |
| **Project** | `/p/$projectKey/settings/*` | that project's manage perms | Workflow/States · Access (members+teams+roles) · Releases · Forms · Project-scoped Fields/Field-rules · Project SLA · Time-logging toggle · Project **overrides** for cascaded scalars |

- **Per-project pages move out of the global dropdown into project-nested routes.**
  States/forms/releases/SLA/time-logging/project-fields become
  `/p/$projectKey/settings/<tab>` with their own sub-nav; the project is the URL
  context, not a `<SelectField>`. The global "Projects" access page is subsumed
  by each project's Access tab (a workspace-level project *index* remains for
  create/archive).
- **Instance settings surface is new.** Secrets stay **env-only** (`config.py`) —
  the Instance surface shows their *status* (enabled/disabled, non-secret config)
  read from a widened `GET /instance`, plus the few genuinely-editable instance
  defaults (§3). No secret is writable through the UI.
- Frontend: a shared `settingsNav(perms, scope)` helper filters nav items;
  `usePermissions()` already exposes `.workspace(p)` / `.project(project, p)`
  (`web/src/lib/hooks.ts:100-121`). Backend keeps enforcing via 403 (defense in
  depth); the nav filter is UX, not the security boundary.

## 3. Scalar settings resolver — override → fallback (the new cascade)

The additive cascade stays for **collections** (custom fields, SLA policies,
labels, builtin rules, views — you extend a set, never replace it). Add a
separate **scalar** resolution path for singleton settings where
`project ?? workspace ?? instance-default` is the right semantics.

- New `scoped_settings(scope ∈ {instance,workspace,project}, scope_id, key, value)`
  table (JSONB value), plus a typed **`SettingKey` StrEnum registry** — each key
  declares its value type, allowed scopes, and instance default. No hardcoded
  magic values (dev-rule 2): a setting *opts into* the cascade by being registered.
- `settings.resolve(session, key, *, project|workspace)` walks project → workspace
  → instance-default and returns the effective value; `settings.set(scope, id, key,
  value)` writes one level. "Not every setting needs a fallback" = only registered
  keys cascade.
- **Initial keys migrated into the cascade** (env → overridable): `work_week_days`
  (today `RADD_WORK_WEEK_DAYS`, instance-only), `timelog_hours_per_day`, plus new
  project-useful scalars as they arise (default priority, require-estimate toggle,
  default SLA calendar). Env value becomes the instance default; workspace/project
  rows override. Existing env-only consumers switch to `settings.resolve`.

## 4. Builtin/system fields become read-restrictable

Spec 36 gave builtin fields **write** rules only (reads stayed open because
builtins render on every list surface). Per the decision, extend them to **read**
too, mirroring custom-field read grants (default-open; any read rule ⇒ whitelist
of role/team subjects, `project.manage` always allowed).

- `builtin_field_rules` gains an `access ∈ {read, write}` dimension (like
  custom-field grants' `FieldAccess`), or a parallel read-rule set; the pure check
  gains `denied_builtin_reads` alongside `denied_builtin_fields`
  (`fields/rules.py:28-52`).
- **The accepted cost — surface-by-surface blanking.** A read-restricted builtin
  must be filtered out of every representation for non-granted principals: item
  hydration (`items/hydration.py`), list/board cells, reports, FTS results, MCP
  tool output, OpenAPI examples. The field registry is the single enforcement
  point for custom fields; builtin fields need the equivalent filter wired at each
  serialization site. UI renders a blanked/"restricted" placeholder rather than
  omitting the column (avoids layout gaps).
- Managed on the same `/settings/field-rules` surface (now `read|write` per
  field × subject), workspace-wide or project-scoped.

## 5. Per-team internal comments (teams narrow the audience)

Comments are binary today (`visibility ∈ {public, internal}`, gated solely by
`comment.read_internal`; `comments/models.py:11-21`, `service.py:162-170`). Add an
optional per-comment team allow-list; **teams narrow, they don't replace** the
permission.

- New `comment_visibility_teams(comment_id, team_id)` join (an internal comment
  may name 0..N teams). Empty = today's behavior (all `comment.read_internal`
  holders).
- **Read rule:** actor may read an internal comment iff
  `comment.read_internal` **AND** (`no teams set` **OR** actor ∈ a named team) —
  with the comment **author** and holders of `project.manage`/project-delete
  always able to read (no one is locked out of their own note; admins retain
  oversight). No one gains internal access they didn't already have.
- Enforce at **every internal-leak surface**, consistently with the existing
  permission gate: `list_comments`, item hydration + comment counts
  (`items/hydration.py`, `items/service.py`), history/activity
  (`items/history.py`), notification fan-out (`notify/consumer.py:188-198`), MCP
  (`mcp/tools.py`). FTS already excludes internal bodies entirely
  (`search/indexer.py:106`) — unchanged. Event stream/webhooks stay unfiltered
  (trusted consumers), same as today.
- UI: a team multi-select on the internal composer
  (`web/src/components/items/CommentsThread.tsx`); a "visible to: Team A, Team B"
  chip on restricted internal comments.

---

## Slicing (each row is independently shippable + demoable; dev-rule 5)

1. **Permission CRUD refactor** — enum atoms + umbrella expansion + scope map +
   builtin-role migration + roles-matrix UI. Backward-compatible; nothing else
   changes behavior. (Foundation for the rest.)
2. **Settings nav gating** — filter the *existing* flat nav by scope perms. Quick,
   visible win; no route moves yet.
3. **Project-nested settings routes** — move per-project pages under
   `/p/$projectKey/settings/*` with a project sub-nav.
4. **Instance settings surface** — new shell + widened read-only `GET /instance`.
5. **Scalar settings resolver** — `scoped_settings` + `SettingKey` registry +
   migrate `work_week_days`/`timelog_hours_per_day` as the first cascaded scalars.
6. **Builtin-field read grants** — `access` dimension + surface-by-surface blanking.
7. **Per-team internal comments** — join table + narrowed read gate + composer UI.

Each slice: Alembic migration where models change, `docs/modules.md` row/line
update in the same change (dev-rule 3), and a core-invariant test for the pure
decision functions (CRUD expansion, scalar resolution order, builtin-read denial,
comment-team read gate) — not per-endpoint tests (dev-rule 4).

## Known simplifications / deferred (as built)

- **SUPERSEDED IN PART by spec 67:** the three-level scalar
  cascade (§3) collapsed to two scopes — INSTANCE defaults → PROJECT overrides
  (`SettingScope.WORKSPACE` removed; workspace rows migrated to instance).
  The three-surface IA (§2) also shifted: the workspace "General" tab now
  edits the INSTANCE scope, the Instance tab ("Server") is deploy status only,
  and SLA policies moved under project settings. See
  `67-two-scope-settings.md`.
- **Workspace stays single** (no switcher) — org-default layer only; true
  multi-workspace remains the PLAN §9 "revisit if multi-tenant hosting."
- **Secrets stay env-only**; Instance surface is status + safe scalar defaults, not
  a secrets editor.
- **No workspace-level custom-role assignment** still (the separate spec-36 gap);
  CRUD atoms reach users via project roles / widened member scope / adminship.
- **Config resources expose create/update/delete, not read** — config reads stay
  open to members (the open-visibility default). Value-level read restriction lives
  in the field-grant (custom + builtin) and comment-visibility systems, where it
  matters. `title/state/priority` are never read-restrictable (structural row ids).
- **CRUD split, as built**: content resources gained the missing `delete` atom;
  config resources gained enforced `create/update/delete`. Content `create` vs
  `update` for comment/worklog/doc keep their existing single "write" verb (no
  create-vs-edit capability distinction in the domain) — items keep their real
  create/update split.
- **Scalar cascade shipped with `work_week_days`** (fully wired: SLA per item
  project + `GET /instance`). The registry takes N keys; `timelog_hours_per_day`
  is a trivial add once its sessionless duration helpers are threaded a scope.
- **Builtin-read blanking** covers item hydration (boards/lists/detail). Reports,
  FTS result rows, and MCP tool output are follow-up surfaces (MCP comment reads
  already go through the filtered `list_comments`).
- **Per-team internal comments**: enforced on the REST list, notify fan-out,
  history feed, and MCP. `comment_counts` stays a plain count — a team-restricted
  internal comment may be over-counted in the badge (a number, never body text).
- **No events for scoped-settings** yet (admin-low-frequency); add if the audit
  log needs them.
