# Spec 17 — intake forms (backend, Wave 2)

Template-scoped forms that capture structured intake and create a work item (the Proposal /
artist-support flow). Depends on spec 14 only for cycle/release defaults (optional — skip if not
landed, gate behind presence).

Allowed paths: `server/src/radd/modules/forms/` (new), `server/src/radd/modules/auth/authz.py`
(add `Permission.FORM_MANAGE`), `server/src/radd/config.py` (modules tuple),
`server/migrations/versions/` (ONE revision), `server/tests/test_forms.py` (new),
`server/scripts/demo_forms.sh` (new), `docs/modules.md`.

A sibling migration head may exist (spec 15 in parallel) — `alembic upgrade heads`, do NOT merge.
Never touch port 8000; verify on 8001/8002, kill exact PIDs. Explicit pathspec commits.

## Model

- `forms`: id, project_id FK, name, description (Text default ""), enabled bool default true,
  `fields` (JSONB: ordered list of `{field_key, label_override?, help?, required}` — `field_key`
  references a registry field definition in the project's scope, validated on write; a form field
  can be required even if the underlying registry field isn't), `defaults` (JSONB:
  `{kind?, state_name?, priority?, labels?[], assignee_email?, cycle_name?, release_version?}`
  applied to created items), `title_prompt` (String, default "Summary"), timestamps.
- Validation on write: every `field_key` exists in the project's field scope (409 unknown);
  defaults resolve (unknown state/label just stored, resolved at submit; unknown assignee 409).

## Endpoints

- CRUD `GET/POST/PATCH/DELETE /forms?project_id=` gated on `FORM_MANAGE` (workspace admins + builtin
  admin/member — members can create intake forms for their projects); `GET /forms/{id}` open to
  `ITEM_CREATE` on the project so submitters can render it.
- `POST /forms/{id}/submit` {title, values:{field_key: value}} → creates a work item in the form's
  project: title from the payload, defaults applied, custom_fields = validated submitted values
  (run the registry `validate_custom_fields` + the form's own `required` overrides → 422 with the
  offending fields). Gated on `ITEM_CREATE` on the project (v1 = authenticated members only; note
  "public/tokened submit" as a deferred gap). Returns the created ItemRead.
- Events `form.created/.updated/.deleted` and the normal `item.created` from the submit.

## Verify (demo_forms.sh, 8001)

Seed+login; create a project + a couple of select fields; create a form (2 fields, one required via
override, defaults: kind=issue, a label, a state); render `GET /forms/{id}`; submit valid values →
item created with the defaults + values; submit missing the required field → 422 naming it; submit
an unknown field value → 422 from the registry. `uv run pytest` green;
demo.sh/webhooks/permissions/views regression green.

Report: migration id, the submit validation flow, verification output, deviations, gaps.
