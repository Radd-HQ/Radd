# Spec 07 — field permissions by role/team + internal comments (backend, after spec 06 lands)

Allowed paths: `server/src/radd/modules/fields/`, `server/src/radd/modules/comments/`,
`server/src/radd/modules/items/` (read/write path call sites + hydration ctx only),
`server/migrations/versions/` (one revision on current head), `server/scripts/demo_permissions.sh`
(new file), `server/tests/test_field_grants.py` (new — this is registry core, tests warranted),
`docs/modules.md`.

Prereq: spec 06 landed — use `authz.subjects_for(session, user, project)` → `{role_ids, team_ids}`
and `authz.effective_permissions(...)`; `Permission.COMMENT_READ_INTERNAL` exists.

## Field permission grants

- New table `field_permissions`: id, field_id FK (ondelete CASCADE), subject_type
  (`FieldSubject` StrEnum: role|team), subject_id UUID, access (`FieldAccess` StrEnum: read|write),
  unique(field_id, subject_type, subject_id, access).
- Semantics (document in modules.md):
  - No rows for a field+access → default: read open to anyone with item.read; write open to
    anyone with item.update.
  - Read rows exist → readable only if one of the user's subjects (roles incl. builtin-derived,
    teams) holds a read OR write grant, or the user has project.manage.
  - Write rows exist → writable analogously via write grants only.
- Replace `min_read_role`/`min_write_role`: migration converts non-default values into grants
  against the workspace's builtin roles (min_read_role=admin → read grants for builtin admin;
  min_write_role=admin → write grant for admin; member → admin+member), then drops both columns.
- API: FieldDefinitionRead gains `permissions: [{subject_type, subject_id, access}]`;
  `PUT /api/v1/fields/{id}/permissions` (full-list replace, project.manage on the field's scope,
  validates subjects belong to the same workspace) + emits `field.updated`.
- fields service: `readable(defs, ctx)` / `writable_check(defs, values, ctx)` where ctx carries
  `{role_ids, team_ids, has_manage}` — pure, unit-tested. Items call sites updated (they already
  call these; adjust signatures). OpenAPI augmentor: replace x-min-* with `x-restricted: true`
  on fields that carry any grant rows.

## Comment visibility

- `comments.visibility` (`CommentVisibility` StrEnum: public|internal, default public,
  migration backfills public).
- Create accepts `visibility`; creating internal requires COMMENT_READ_INTERNAL. GET filters
  internal comments out for users without the permission; PATCH/DELETE of internal comments
  require it too (plus existing author/admin rule). CommentRead includes visibility.
- `comment_count` on items: count only comments visible to the requesting user (hydration
  already receives the actor via ctx — thread a `can_read_internal` flag).
- Events carry visibility; excerpt for internal comments still goes to the trusted stream
  (note in modules.md).

## Verify

`demo_permissions.sh` (new, port-8001 pattern like other demos, seed admin login): field with
read granted only to a "leads" team → team member sees it, non-member doesn't, non-member write
→ 403; write-granted-role scenario; internal comment invisible to viewer-role user and visible
to member; comment_count differs accordingly. pytest green (existing + new). demo.sh +
demo_webhooks.sh regression green. Never touch port 8000; kill only exact PIDs; commit with
explicit pathspecs.
