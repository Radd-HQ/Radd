# Spec 95 — Compact inline-token multi-select (app-wide)

**Status:** done + verified. A UX consolidation: replace the tall, wrapping stacks of
removable pills with ONE shared inline-token control, used everywhere a flat value-SET is edited.

## Why

Multi-value editors each rendered every selection as a wrapping pill stack that grew tall with many
values, and there was **no shared multi-select** — `ScopePicker` did projects only, `SubjectPicker`
is single-select, and every other surface rolled its own. The user asked for a single compact style
app-wide: chips on ONE row that scrolls sideways, a typeahead input, and an autocomplete dropdown.

## The component — `web/src/components/TokenMultiSelect.tsx`

One control, one row tall regardless of count:
- Selected values are chips on a single `overflow-x-auto` row; a typeahead `<input>` at the end.
- Props: `value: string[]`, `onChange`, `options: TokenOption[]` (`{value,label,hint?,group?,icon?}`),
  `allowCreate` (free-text sets), `disabled`, `invalid`, `placeholder`, `ariaLabel`, `id`.
- Autocomplete dropdown filters `options` by label+hint; optional **grouped** headers (e.g.
  People/Teams); a "Create …" row when `allowCreate` and the term matches nothing.
- Keyboard: ↑/↓ move the highlight, Enter/comma add, Backspace removes the last chip, Esc closes; each
  chip has an ×. Values not in `options` show their own text as the chip label (free-text round-trips).

## Adopters (flat value-set multi-selects)

Tall-pill offenders → `TokenMultiSelect`: **issue labels** (`LabelsEditor`, now with existing-label
autocomplete + create), **custom-field options** (`OptionsEditor`), **custom multi_select fields**
(`CustomFieldsForm` — the chips + dropdown variants collapse into one widget), **team managers**
(`TeamStewardship`), **portal form sharing** (`FormSharing`), **instance-wide role holders**
(`RoleGlobalGrants`). The user/team pickers encode kind in the value (`"user:<id>"` / `"team:<id>"`)
and group People/Teams. Already-compact ones unified for consistency: **`ScopePicker`** (projects;
empty = Global via the placeholder) and the custom-field "N selected" dropdown.

Left as-is (a line edit would regress them): checkbox grids (permissions matrix, workflow
transitions, cycle visibility, notification prefs), per-row builders that carry per-row data (access
grants, view/dashboard shares, form fields), and small fixed toggle-sets (weekday schedule, SLA
priorities, comment visible-to). The now-dead per-field "Chips vs Compact dropdown" chooser in
`Settings → Fields` was removed (the `field.display` column stays on the model, unused for rendering).

## Verified

Headless (New Field modal): ScopePicker adds a project chip; switching Type to multi_select shows
OptionsEditor; six free-text options add as chips and the row stays **32px (one row, not a stack)**;
× removes; typing a new value shows the Create row. Full host build clean.
