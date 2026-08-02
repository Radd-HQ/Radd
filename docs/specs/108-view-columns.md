# Spec 108 — List views become real tables: columns, resizing, a column picker

User ask: list-type views should show items as COLUMNS — resizable, with the
visible set picked from the available fields — "the display menu is a little
limited".

## Where the column setup lives (the decision)

- **The column SET (ids + order) is part of the saved view** — a new nullable
  `views.columns` JSONB (migration `c108c0lumns`, the `wip_limits` template:
  Create/Update with the model_fields_set omitted/null idiom, `Read.columns`,
  `_validate_columns` trims/dedupes/caps at 16, ids validated LOOSELY — a
  custom field can leave the registry and a stale id must degrade, not brick
  the view). Editing rides the existing view-edit gate, so a curated view
  shows every teammate the same table. NULL = the view type's default set
  (mirroring the old slot presets, so existing views feel unchanged; queues
  default to their reporter/SLA feel).
- **Widths are per-user** localStorage (`radd.view.<id>.column-widths`) — pure
  ergonomics, per the url-state.ts design line; the key contains the view id,
  so "Reset view" sweeps it for free.

## The table (SPA)

- `lib/columns.ts`: the column catalog — 18 builtins (type, parent, labels,
  cycle, release, both dates, team, priority, assignee, reporter, sla, points,
  progress, logged_time, created, updated, state) + every custom field in the
  view's scope as `cf.<key>` (all-projects views: global fields only), each
  with a default/min width; `resolveColumns` drops unknown ids;
  `useColumnWidths` (live during drags, persisted on release).
- `components/views/ColumnCells.tsx`: one sticky header row with drag
  handles, and one typed cell per (column, item). **FIT-TO-WIDTH geometry**
  (third cut — the first was right-anchored and dragging felt reversed, the
  second left-anchored with horizontal scroll, which the user rejected: the
  app must stay the width of the screen): the row always spans exactly the
  container — the Item zone (selection/star/kind/flag/key/title) FLEXES to
  absorb the slack, cells are `flex-basis: width` and compress toward their
  minimums when space runs short, and a handle sits on each internal
  BOUNDARY: dragging TRANSFERS width across it (left grows exactly what the
  right shrinks), so the handle tracks the cursor and no drag can ever
  produce a horizontal scrollbar; the last column's edge is the screen edge —
  no handle. Boundary drags patch BOTH neighbours atomically
  (`applyWidths`/`commitWidths`); double-click resets the pair (detected via
  pointerdown click-count — `preventDefault` in the drag helper suppresses
  real dblclick events). The sticky header's wrapper paints an opaque bg-base
  block over the scroll padding, so rows vanish under it instead of peeking
  above ("flying over"). Cells — chips reused from ItemBadges, custom fields rendered per
  registry type (booleans Yes/No, durations via the instance duration config,
  select chips, user-field ids resolved to names via a directory fetch that
  only fires while such a column is visible, urls as stop-propagation links).
  Empties render a quiet dash so the grid reads as a grid. Custom-field
  values already ride every list row (`item.custom_fields`) — zero new
  per-row fetching.
- `ViewList` renders the header + cell clusters for list/planning/queue views
  (boards keep their card slots; the legacy slot path remains for
  column-less callers). The queue's hardcoded `QueueRowMeta` columns became
  ordinary default columns. SLA/rollup/timelog batches now condition on the
  COLUMN set for list surfaces (slots still gate boards).
- `DisplayMenu` grows a **Columns** editor for list surfaces: ordered rows
  (↑ ↓ ×) + an "Add a column…" select over the catalog, PATCHing
  `view.columns` when the actor can edit the view; read-only otherwise, with
  the note "Columns are part of this view… widths are yours: drag the header
  edges". Label-cap and scale stay personal.
- The copy-pasted drag-resize logic (roadmap label gutter, peek drawer)
  extracted into `lib/drag.ts startHorizontalDrag` — both refactored onto it;
  column handles are the third consumer.

Width hygiene (same day, after a dragged-wild width left a huge trailing
gap): stored widths CLAMP to their column's [min, max] on read (stale values
from older layouts can never blow the table out), a boundary DOUBLE-CLICK
snaps its pair back to defaults, and the Display menu's "Reset to defaults"
clears the personal width map alongside the card display.

## Tests / verification

`test_board_depth.py`: columns round-trip (trim/dedupe/order), explicit-null
reset, omitted-unchanged. 1257 total. CDP proof on the dev DEV List view:
7 header handles with the right labels, drag grew Issue type 96→156px and
persisted `{"type":156}` under the view-scoped key, the Display menu shows
the Columns editor + shared-set note, zero console errors — and the
screenshot shows cells aligned down all 200 loaded rows.
