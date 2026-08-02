# Spec 52 — Issue mentions + per-field widgets

**Status: SHIPPED.** Two editor/field-UX features.

## 1. Issue mentions (`#` everywhere)
Alongside `@[Name](uuid)` people-mentions (spec 29), the markdown editor now
autocompletes ISSUES on a `#` trigger and renders references as links — in
comments, doc pages, item descriptions, anywhere the editor + renderer are used.

- **Editor** (`MarkdownEditor`): typing `#TD-…` (or any text) after a boundary
  opens an issue picker sourced from the workspace search (`GET /search`, the
  Cmd-K palette endpoint — no new backend). Selecting inserts `#[TD-1234](TD-1234)`.
  Arrow/Enter/Tab/Escape drive it, mirroring the people-mention flow; the editor
  reads `useCurrentWorkspace()` so it works without prop-threading.
- **Renderer** (`markdown.tsx`): a new `#[label](KEY)` token (KEY = `[A-Za-z]+-\d+`)
  added to `INLINE_RE` BEFORE the generic link pattern (so `#[…]` matches as one
  token, not a broken relative link) → renders a sky-tinted chip-link to
  `/issues/KEY`.
- **Deferred**: no persistent back-reference yet (the referenced issue doesn't get
  a "referenced by" backlink) — the inline clickable reference is v1; parsing on
  save into `item_links`/`weblinks` is a follow-up.

## 2. Per-field render widget (fix chip overflow)
Multi-select custom fields rendered every option as a toggle chip, which fills
space when a field has many options. Fields now carry a `display` hint.

- `field_definitions.display` (nullable `FieldDisplay`: `chips` | `dropdown`;
  NULL = the type default). Migration `f6cb41ece0f1`.
- New `PATCH /fields/{id}` (`FieldDefinitionUpdate` — name + display; key/type/
  options stay immutable) gated by `field.update`. `create_field` accepts it too.
- **Frontend**: `CustomFieldsForm` renders a multi-select as the existing chips
  OR a compact `MultiSelectDropdown` (a button + popover checklist showing
  "N selected") when `display = dropdown`. The fields settings editor gets a
  per-field **Widget** toggle (Chips / Compact dropdown) on the expanded row.

## Known follow-ups (from the same request, not yet built)
- **Field default values** — a `default_value` on field defs, applied on item
  create + editable inline in the fields table (the OtherTracker "Default value"
  column). Needs a column + apply-on-create; the `PATCH /fields/{id}` seam is
  already in place to edit it.
- **Comprehensive settings pass** — info banners + reorder shipped on the config
  editors; a full sweep of every settings page (inline default editing, slide-in
  "Create new / Use existing" add panel) remains.
- **Select (single) widget** — `display` currently only branches multi_select;
  single-select could add a radio/segmented variant.
