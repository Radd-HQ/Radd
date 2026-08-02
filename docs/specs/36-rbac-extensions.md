# Spec 36 — RBAC extensions: per-entity actions, builtin-field rules, wider floors

Three RBAC growth steps in one wave, all backward-compatible.

## 1. Per-entity action permissions

New `Permission` members so roles can grant entity management WITHOUT full
project/workspace admin: `state.manage`, `release.manage`, `field.manage`
(project-scoped) · `label.manage`, `webhook.manage`, `canned.manage`
(workspace-scoped). The routers for those entities now check the granular
permission, and **umbrellas imply their per-entity actions**
(`IMPLIED_PERMISSIONS` + `expand_permissions`, applied in the pure decision
core): `project.manage` ⇒ state/release/field manage; `workspace.manage` ⇒
label/webhook/canned manage. Granular grants do NOT imply the umbrella.
Migration `43c250fb2a01` mirrors the grown definitions into stored builtin
role rows (the immutability contract: rows == seed definitions).

## 2. Wider builtin floors (the long-tracked gap)

- Workspace-scope member checks now use `WORKSPACE_MEMBER_SCOPE` = floor +
  **`cycle.manage` + `timesheet.view`** — plain members run sprints and see team
  timesheets. (The per-project floor is unchanged.)
- The builtin **member role gains `form.manage`** (backfilled) — members author
  intake forms.
- **`automation.manage` and `sla.manage` stay admin-only deliberately**: rules
  execute as the SYSTEM actor, so authoring them is privilege-bearing.

## 3. Builtin-field write rules (RBAC per field, beyond custom fields)

Spec 07 gave CUSTOM fields per-field grants; this extends per-field access to
BUILTIN item fields with the same default-open philosophy:

- `builtin_field_rules` (workspace_id, project_id NULL = workspace-wide,
  `field` ∈ `BuiltinItemField` (title/description/state/priority/assignee/
  reporter/team/labels/parent/dates/cycle/release/flagged), subject = role|team).
- **No rules on a field = write-open** to `item.update` holders (the default).
  **Any rule = only its subjects** (or `project.manage`) may change that field —
  enforced in `create_item`/`update_item` via the pure `denied_builtin_fields`
  (tested), 403 `no permission to write fields: priority, …`.
- Reads stay open (hiding builtin fields would break every list surface; custom
  fields already support read grants where hiding matters).
- API: `GET/PUT /field-rules?workspace_id[&project_id]` (full-list replace,
  `field.manage` on scope, subjects validated against the workspace, emits
  `field_rule.updated`). UI: **/settings/field-rules** (scope picker, field ×
  role/team rows, save).

## Known simplifications

- No workspace-level custom-role assignment surface yet (workspace roles remain
  admin/member) — granular workspace-scoped permissions currently reach users
  only via the widened member scope or adminship; a `workspace_member_roles`
  join is the next step if needed.
- Builtin-field rules are write-only and unconditional (no SLQ conditions like
  "only in Triage" yet — the rule model leaves room for a `condition_slq`
  column).
- The item-detail UI doesn't pre-disable rule-restricted controls (rules aren't
  exposed to non-managers); the 403 names the field after the attempt, same as
  custom-field grants.
