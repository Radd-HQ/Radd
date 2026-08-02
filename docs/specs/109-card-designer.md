# Spec 109 — The card designer: per-view board-card layout + a preset library

User ask: a "card designer" in the board view settings — pick WHICH attributes
show on the card and WHERE, in a dynamic drag-a-slot layout editor, set per
board, savable as presets. Decisions locked with the user up front: a free
grid layout model, a drag-on-live-preview editor, and an instance-wide
copy-on-apply preset library.

## Where the layout lives (the decision)

- **The card layout is part of the saved view** — a new nullable
  `views.card_layout` JSONB (migration `d109cardlay`, the spec-108 `columns`
  precedent end to end: Create/Update with the model_fields_set omitted/null
  idiom, `ViewRead.card_layout`, loose attr-id validation so a departed custom
  field degrades to an empty cell instead of bricking the view, write path
  behind the existing view-edit gate). NULL = the type's default card —
  `DEFAULT_BOARD_CARD_LAYOUT` is a faithful translation of the old hardcoded
  anatomy, so untouched boards render pixel-identically AND keep tracking the
  default if it evolves (Save PATCHes null when the draft equals it).
- **Personal ergonomics stay personal**: the zoom scale keeps living in
  localStorage (`useCardDisplay`, now scale-only for boards). `max_labels`
  moved INTO the layout — the labels row's height is part of the designed
  card, and a preset must be able to capture "Compact = 1 label".

## The grid model (stored) vs the lane renderer (drawn)

`{v: 1, cells: [{attr, row, col, span, align}], max_labels}` on an **8-column
grid** (320px card ⇒ ~37px tracks: hittable drop zones, and the old footer's
seven chips fit one row). `attr` = `title` | a `lib/columns.ts` builtin id |
`cf.<key>`; pydantic owns shape (row/col 0-7, span 1-8, ≤24 cells → 422),
`_validate_card_layout` owns semantics (409): duplicate attrs, exactly one
`title` cell (mandatory — the designer renders it without a remove), col+span
overflow, same-row range overlap.

A literal `repeat(8, 1fr)` CSS grid could NOT reproduce the old card (its
footer is a packed wrapping flex line with an `ml-auto` right cluster, and
grid tracks are column-global across rows), so the renderer draws each
occupied row as an independent **flex lane**: cells sorted by col, the first
`align:"end"` cell takes `ml-auto`, empty rows collapse. Span is therefore a
width HINT — growable attrs (title, labels) get `flex-grow` + a basis, chips
keep natural width (span > 1 = a min-basis). Structural chrome is never a
cell: selection checkbox, TypeChip-else-KindBadge (so `type` left the
placeable set), key link, star, flag. **Row 0 is the header lane** — its
start cells render after the key, end cells after the flag (how the default
keeps priority top-right). Lane top-margins key off the STORED body-lane
ordinal (1.5/2/2.5 rhythm survives an empty middle lane — exactly the old
labels-absent behavior).

## Renderer (SPA)

- `lib/card-layout.ts`: types + constants, `activeCardLayout` (defensive
  parse, malformed → default), `lanesOf`, `placedAttrSet`,
  `isDefaultCardLayout`.
- `components/board/card-cells.tsx`: ONE attr→chip registry
  (`renderCardCell`) shared by BoardCard, swimlanes and the designer preview —
  the old board-local chips moved here; `progress` folds the previously
  structural ChildCount (bar when the rollup lands, count before it);
  reporter/start_date/created/updated joined the card vocabulary from the
  column catalog; `cf.<key>` renders through `CustomCell`, extracted from
  ColumnCells into `components/items/CustomFieldValue.tsx`. Empty value →
  null → the cell renders nothing.

**Uniform heights (follow-up — supersedes the launch behavior):**
the first cut collapsed all-empty lanes (the old `hasFooter`) and let
one-line titles shrink the card, which made column card heights ragged. Now a
card's height comes from the designed LAYOUT, not the data: an all-empty lane
still reserves one chip row (`min-h-5`), and the title always reserves both
clamped lines (`min-h-[2.75em]` = 2 × leading-snug). CDP-measured on the dev
board: 200/200 cards at exactly one height. Residual variance is only real
content wrapping (a labels or footer lane spilling to a second line), which
no static reservation can predict. This deliberately trades the launch-day
pixel parity for consistency — a product decision, not a regression.
- `BoardCard` kept its draggable/peek/context shell and fixed header; the
  hardcoded rows are gone. ViewBoard + ViewSwimlanes pass `layout` (+
  usersById/cfByKey for cf cells); batches (sla/rollup/logged_time, plus the
  cf-user directory fetch) now gate on `placedAttrSet` for boards.

## The designer (`components/views/carddesigner/`)

Entry: the board Display popover's slot grid is REPLACED by "Design card…"
(the layout is shared — a personal checkbox can't know where a chip goes);
scale stays in the popover, planning surfaces keep their checkboxes. The
modal (`Modal extraWide`, a new 768px size) is WYSIWYG by construction: the
preview renders the ACTUAL lane renderer + cell registry over a fully
populated `SAMPLE_ITEM` (synthesized values for every in-scope custom field).

- `layout-ops.ts` — pure ops returning normalized layouts or null (ignored):
  `placeCell` (collision = push-right while it fits), `removeCell` (title
  refuses), `resizeCell` (clamped to grid + right neighbour), `toggleAlign`,
  `nudgeCol`/`nudgeRow` (the keyboard fallback: arrows move, +/− resize,
  Delete removes — on the click-selected cell).
- `AttrPalette` — grouped chips from `columnCatalog` (Work item / People /
  Dates / Delivery / Custom fields) + search; placed = dimmed (one instance
  each); stale placed ids get the amber registry warning. Drag onto the
  preview (house `useBucketDrop`, no new dependency: 8 column zones per lane
  + insert-row bands overlay during a drag) or click to append.
- Cells drag to move, hover-✕ remove, right-edge span handle
  (`startHorizontalDrag`), align toggle on the selected cell. Read-only for
  non-editors ("only view editors change it"). The modal body never scrolls
  (HTML5 dnd has no autoscroll) — only the palette does.

## Presets (instance library, copy-on-apply)

`card_layout_presets` (id, name, layout JSONB, position — the CannedResponse
shape) in the views module; `GET/POST /views/card-presets` +
`PATCH/DELETE /views/card-presets/{id}` registered BEFORE `/views/{view_id}`
(the /counts literal-segment precedent). Reads ride `item.read`; writes ride
new `cardpreset.create/update/delete` atoms — one `ResourceSpec("cardpreset",
GLOBAL, …)` line in auth's CRUD_RESOURCES (umbrella `cardpreset.manage`,
implied by `global.manage`, so admins hold it with zero backfill). Applying a
preset COPIES the layout into the draft — a snapshot, so editing a preset
later never restyles existing boards (the delete confirm says as much).
No seeded presets: NULL-means-default already covers out-of-the-box.
Events: `view.card_preset.created/updated/deleted`.

## Tests / verification

`tests/test_card_designer.py`: layout round-trip + explicit-null clear +
omitted-unchanged, the four semantic 409s, shape 422s (span 0 / row 9 / >24
cells), preset CRUD + empty-layout refusal, `global.manage` expansion carries
the cardpreset atoms while a plain member 403s at the create gate. 1262
total. CDP proofs against the dev instance: (1) parity — 200 default-layout
cards probed: padding 12px, title mt 6px + line-clamp 2, body-row margins
only 8px/10px, footer wraps with the ml-auto cluster, no-labels cards keep
the 10px footer; (2) a PATCHed custom layout (reporter row, points, state
right) renders on every card with labels/priority gone, the designer modal
mounts with the stored draft + palette + presets, then PATCH null restores.
Screenshots eyeballed both ways.
