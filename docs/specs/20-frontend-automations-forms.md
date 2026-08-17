# Spec 20 — frontend: automations rule builder + intake forms (Wave 3c, run AFTER 19)

Allowed paths: `web/` + frontend row in `docs/modules.md`. Runs SEQUENTIALLY after spec 19 lands
(shares web/ files — rebase on committed state). Backend LIVE on :8000 — build against real
`/openapi.json`.

Contracts: `GET/POST/PATCH/DELETE /automations?workspace_id=` (rule: {id, name, enabled, trigger:
item_created|item_updated, condition_slq, actions:[{type, params}], position}), `POST
/automations/{id}/test {item_id}` → dry-run preview of which actions would apply; needs
`automation.manage` (workspace/instance admin). ActionTypes: set_state, set_priority, set_assignee,
set_team, add_label, remove_label, set_cycle, set_release, set_custom_field, add_comment.
Forms: `GET/POST/PATCH/DELETE /forms?project_id=` (form: {id, name, description, enabled, fields:
[{field_key, label_override, help, required}], defaults, title_prompt}), `GET /forms/{id}`,
`POST /forms/{id}/submit {title, values}` → created ItemRead; create/edit needs `form.manage`,
submit needs `item.create`.

## Deliverables

1. **Automations** — `/settings/automations` (workspace, gated `automation.manage`): rule list
   (name, trigger, enabled toggle); a rule editor (`components/automations/`): name, trigger select,
   an **SLQ condition** field REUSING the existing `SlqEditor` (with autocomplete — pass the
   workspace suggestScope), and an **actions builder** — an ordered list of action rows, each an
   action-type select + type-specific param inputs (state/priority/assignee/team/label/cycle/release
   pickers pulling the relevant `GET`s; custom-field key+value; comment body+visibility). A "Test on
   an item" affordance: pick an item, call `/test`, show which actions would apply. Save via POST/
   PATCH; delete with confirm.
2. **Intake forms** — `/settings/forms` (per-project, gated `form.manage`): form list; a form editor
   (name, description, title_prompt, an ordered picker of registry fields to include — each with
   label_override/help/required toggle, from `GET /fields?workspace_id`, defaults editor:
   kind/state/priority/labels/assignee/cycle/release). AND a **submit page** `/p/$projectKey/forms/
   $formId` that renders the form (`GET /forms/{id}`) as a clean intake form — title input + a field
   per the form's `fields` (rendered by registry type, required marked) — and submits
   (`POST /forms/{id}/submit`), showing the created item's key + a link to its issue page; 422s
   (missing required / bad value) rendered per field. A "New from form" entry could live in the
   sidebar or project header.
3. Types/queries/constants/routes/sidebar for both.

Environment: npm PATH the session scratchpad;
Playwright at scratchpad/pw-browsers; seeded admin <local dev credentials> (holds
automation.manage + form.manage as instance admin). Create test entities prefixed SPEC20 and clean
up rules/forms you make (both have DELETE). Never touch port 8000's process; vite 5173 killed by
exact PID; final `npm run build` refreshes the :8000 bundle. Commit `-- web docs/modules.md` only,
message ends `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

Done = `npm run build` zero TS errors + Playwright evidence: build a rule (trigger + SLQ condition
via the autocomplete editor + 2 actions), run /test preview, save (API-confirmed); build a form and
submit it from the submit page → created item shown, with a 422 path on a missing required field.
Screenshots of the rule editor and a submitted form. Report.
