# Spec 96 — Disable un-writable fields up front (resolved writability)

**Status:** done + verified. Extends the spec-92 access framework: a field/control the
user can't write is **disabled + dimmed-but-readable up front** (no lock icon; a hover `title` gives
the reason), never editable-then-403-on-save. Comment composer: a note when `comment.write` is absent.

## The gap

The client couldn't predict field writability — write grants + the actor's subjects aren't exposed
to the SPA, so resolution happened only at save time and a denied write surfaced as an inline error
AFTER editing (`web/src/lib/api.ts` said so explicitly). Views/dashboards already shipped resolved
`can_edit`/`can_manage`; items/fields lacked the equivalent.

## Backend — one resolved signal (`fields` module, all via `access`/RBAC)

- `fields.service.readonly_field_keys(session, project, *, user_id, role_ids, team_ids, has_manage)`
  → the builtin field NAMES + custom field KEYS the actor may NOT write in a project. Custom via
  `field_writable`/`build_field_ctx`, builtin via `builtin_write_denied` — the SAME resolvers the
  write path uses; project-manager (`PROJECT_MANAGE`) bypasses. It is per-(actor, project) and
  **item-INDEPENDENT** (field grants are project/global-scoped, never per-item), so it's cheap and
  covers every item/board/list surface.
- `GET /fields/writable?project_id=` → `{ readonly_fields: [...] }` (`FieldWritabilityRead`). Any
  signed-in user (their own verdict); cached per project on the client.
- Tests: `server/tests/test_field_writability.py` — custom + builtin write grants reflected; team
  membership and project-manager bypass clear them; a project-scoped grant is read-only only in its
  project; no grants = nothing read-only.

`item.update` and `comment.write` are already in the permissions union (`Project.permissions`), so
those coarse gates are frontend-only. Workflow-state transitions keep their per-item
`/items/{id}/allowed-transitions` gating.

## Frontend — `useItemWritability(project)` (`web/src/lib/hooks.ts`)

Returns `{ canEdit (item.update), fieldWritable(name), restricted(name), reasonFor(name) }`.
- EDIT surfaces use `fieldWritable(name)` = item.update AND not grant-restricted.
- The CREATE modal (already gated by `item.create`) uses `restricted(name)` (grant-only).
- Disabling: a whole rail field wraps in `<fieldset disabled>` (natively inert + dimmed);
  `SelectField`/`TextField` gained a `disabled:opacity-70` dimmed-readable look; `TokenMultiSelect`/
  `LabelsEditor`/`CustomFieldsForm` take a `disabled`/`lockFor` prop.

**Surfaces gated:** the issue-detail properties rail (every builtin + custom field), title,
description, flag; the comment composer (a "you don't have permission to comment" note); the
**bulk-action bar** (per field, on single-project selections — cross-project keeps the server's
per-item skip/report); the **New Item modal** (the fields a grant restricts). Boards/lists are
display-only (drag was already gated); settings controls already disable/hide on missing permission.

## Verified

Headless as real restricted members (Member role globally; a custom field + `priority` write-locked
to the Admin role): the locked field(s) render disabled while unrestricted fields + Priority + Title
stay editable and the composer shows; the bulk bar disables the locked Priority action while Assignee
stays enabled; the create modal disables the write-locked custom field + Priority while an open field
+ Assignee stay editable. 980 backend tests green.
