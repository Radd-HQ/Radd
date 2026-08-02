# Spec 61 — Workflow transitions with validation guards

Service-desk wave, part 1 — but deliberately general: instead of a JSM-style
"approvals" bolt-on, the workflow module gains an OPTIONAL transition graph with
per-transition validation rules, usable by service-desk AND development projects.
Canonical example: "you cannot move Triage → In Progress without an assignee and
an estimate." Approvals-style gates ("only after review") are expressible as a
guarded transition; a dedicated approver concept stays out of scope.

## 1. Enforcement mode (scalar setting, spec-50 cascade)

- New `SettingKey.WORKFLOW_TRANSITION_MODE` (STRING; scopes instance/workspace/
  project; config default `workflow_transition_mode = "off"`), values =
  `TransitionMode` StrEnum (workflow/types.py):
  - `off` — feature disabled, nothing enforced (the default; fully optional).
  - `guards` — every state change is allowed UNLESS a matching transition row's
    rules fail. Lets a dev project add one guard without defining a full graph.
  - `strict` — additionally, when a project has ANY transition rows, a state
    change is allowed ONLY if a row matches (from, to). Service-desk lockdown.
- Resolved per item project at check time via `settings_service.resolve`.

## 2. Transition rows (`workflow_transitions`)

- Columns: id, `project_id` (FK CASCADE, indexed), `from_state_id` (FK states,
  NULLABLE — NULL = any source state, the wildcard), `to_state_id` (FK states),
  `rules` JSONB list of `{check, params}` dicts, `position` int. App-level dupe
  check on (project, from, to) — 409 (NULLs make a DB unique constraint moot).
- `TransitionCheck` StrEnum: `require_assignee`, `require_estimate` (an
  `item_estimates` row via the timelogging seam), `require_team`,
  `require_comment` (≥1 comment on the item), `require_fields`
  (params `{"keys": [...]}` — each custom-field key must have a non-empty
  value). Keys validated against the project's field registry on write (409).
- Guard evaluation is PURE (`workflow/guards.py`, tested): an ItemSnapshot
  dataclass (has_assignee, has_estimate, has_team, comment_count,
  custom_fields, field label map) + rules → list of human-readable failure
  strings ('an assignee is required', 'field "Severity" must be set').

## 3. Enforcement (items module change)

- `update_item` captures `old_state_id`; AFTER all patch fields (incl. the
  custom-fields merge) are applied and BEFORE flush/_finish, a real state
  change calls `workflow.check_transition(session, project, item, old_state_id,
  new_state_id)`. Order matters: values arriving in the same PATCH as the state
  change count toward the guards. (Estimates live in their own endpoint, so the
  flow there is: set estimate, then transition.)
- Failures raise `TransitionError` (RaddError subclass; module exception
  handler → 422 `{detail, errors: [...], from_state, to_state}` — same pattern
  as FormValidationError). Applies to EVERYONE including automations and the
  SYSTEM actor (predictability over convenience; noted below).
- Item CREATE is untouched — transitions govern moves between states only.

## 4. API (workflow router)

- `GET /projects/{project_id}/transitions` (member read, same gating as the
  states list) → ordered rows; `POST /transitions`, `PATCH /transitions/{id}`,
  `DELETE /transitions/{id}` gated on `Permission.STATE_MANAGE`. Validation:
  both states belong to the project, from ≠ to.
- `GET /items/{item_id}/allowed-transitions` (item.read) → `{mode, targets:
  [{state_id, allowed, failures}]}` for every project state from the item's
  CURRENT state — the UI's graying/tooltip source. `off` → all allowed.
- Events `workflow_transition.created/.updated/.deleted` (TransitionEvent) +
  automations-catalog rows (admin section).

## Frontend

- Project settings → States page gains a **Transitions** section: the mode
  select (scoped-setting control) + transition rows (from/to state selects,
  rule checkboxes, fields multi-select for require_fields, delete/reorder).
- Issue state pickers consume allowed-transitions: disallowed targets are
  disabled with a tooltip listing the failures; a 422 on PATCH (board drag,
  bulk ops, quick actions — anything that skipped the pre-check) surfaces a
  toast with the failure list.

## Tests (`tests/test_transitions.py`)

Pure guard cases (each check, params, labels); integration: mode off = no-op;
guards block a missing assignee/estimate and pass once satisfied; wildcard
from-NULL row applies from every state; strict blocks an undefined pair but
only when the project has rows; unknown require_fields key 409s on write.

## Known simplifications

- No approver/role checks in v1 — `TransitionCheck` is the extension point
  (add `require_permission` etc. later without schema changes).
- Automations/SYSTEM are NOT exempt: a rule that auto-transitions into a
  guarded state fails visibly in the rule's log rather than bypassing.
- Bulk state changes hit the same per-item 422; the bulk UI reports per-item
  failures without rollback of the successes.
- `strict` only restricts states that HAVE rows for the project (a rowless
  project in strict mode behaves like guards).

As-built notes:

- When BOTH an exact (from, to) row and a from-NULL wildcard row target the same
  state, the exact row alone governs the move (specific beats wildcard — the
  wildcard is the fallback, not an additional gate).
- `allowed-transitions` includes the item's CURRENT state as a trivially-allowed
  target (staying put is not a transition; keeps the select's selected option
  enabled).
- The frontend mode select renders only for `project.manage` holders — reading/
  writing the scalar rides the spec-50 scoped-settings authz, which gates project
  scope on project.manage; transition ROWS are editable with `state.manage` per
  this spec.
- Row reorder is two position-swap PATCHes (no dedicated reorder endpoint).
