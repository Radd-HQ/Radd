# Spec 51 — Issue types (classification axis)

**Status: SHIPPED.** Adds a first-class **issue Type** (Bug/Task/Story/
Feature/Epic…) — the *classification* axis that Radd was missing. Radd already had
the *hierarchy* axis (`ItemKind` = epic/issue/subtask); Type is **orthogonal** to
it (decision: "Type alongside hierarchy", not Jira-style merge). Rendered as a
compact colored chip (a small rounded initial-letter box).

## Backend (`itemtypes` module — mirrors `workflow`)
- `issue_types` table: per-project (project_id FK CASCADE), `name` (unique per
  project), `color` (#rrggbb), `icon` (lucide key, nullable), `position`,
  `is_default` (exactly one per project — set-default clears the others).
- Seeds `DEFAULT_TYPES` (Task*/Bug/Story/Feature/Epic, * = default) on the
  `project.created` in-txn hook. `GET /issue-types?project_id` (item.read) +
  `POST/PATCH/DELETE /issue-types/{id}` gated by the spec-50 CRUD atoms
  `issue_type.create/update/delete` (project-scoped, implied by project.manage).
  Deleting the default 409s (reassign first).
- `work_items.type_id` FK (`ON DELETE SET NULL` — an item survives losing its
  type). `create_item` defaults an untyped item to the project's default type;
  `update_item` sets/clears it (validated to the item's project).
- `ItemRead.type` = `{id, name, color, icon} | null`, batch-hydrated.
- SLQ `type` field: `type = Bug`, `type IN (Bug, Task)`, `type IS [NOT] EMPTY`
  (mirrors `_team`; flows into autocomplete via the catalog).
- Migration `643a19d63157`: table + column + seeds default types into every
  EXISTING project + types every existing item (its project's default) + backfills
  admin's `issue_type.*` atoms.

## Frontend
- Reusable `ValueChip` (colored box + lucide icon or first letter, luma-aware text).
- Type chip on **board cards** + **list rows** (`ItemBadges.TypeChip`), a Type
  **picker** in the **issue rail** (`IssueProperties`) and the **create modal**
  (defaults to the project default type).
- **Issue types** settings tab at `/p/$key/settings/types` — list/create (name +
  color palette) / recolor / rename / set-default / delete, gated on project.manage.

## Known simplifications / follow-ups
- **Priority/State are NOT yet rendered as letter-chips** (they keep their existing
  icon/dot treatment) — the ValueChip is wired for Type; extending it to
  priority/state in the rail + rows is a small follow-up.
- No per-type workflow / field schemes (Jira's per-issue-**type** scheme complexity
  is a deliberate non-goal — custom fields + states stay per-project, not per-type).
- Reorder in the settings editor is by position field only (no drag yet).
- Type is not (yet) a builtin field for spec-36/50 field-rules (no per-type write/
  read restriction) — add to `BuiltinItemField` if needed.
