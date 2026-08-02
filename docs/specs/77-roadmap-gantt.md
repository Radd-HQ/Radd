# Spec 77 — Interactive roadmap (Gantt editing)

Target-features wave, part 10 — the big frontend lift. The roadmap page
(`routes/roadmap.tsx` + `components/roadmap/*`) becomes a real planning editor:
drag to schedule, stretch to resize, parent epics that contain their children,
right-click verbs, and link creation by direct manipulation. NO new data model —
every gesture persists through the existing item PATCH (`start_date`/
`target_date`), rank PATCH, and item-links POST endpoints; SLQ keeps filtering.

## 1. Model (extend `roadmap-model.ts`, stays pure)

- Rows: epics (expandable, chevron state per-project in localStorage) with
  child rows beneath; standalone scheduled leaves; the Unscheduled tray keeps
  holding date-less items (epics AND leaves; a date-less epic with scheduled
  children still draws as a row using the children's span, marked "derived").
- The model gains `dayFromX`/`xFromDay` helpers, a `clampDay` for the padded
  domain, and per-row `bounds` (children min/max) so interaction code stays
  out of the math. Domain padding grows a month past the max bar so bars can
  be dragged into open space; horizontal virtual width recomputes on commit.

## 2. Gestures (pointer events, hand-rolled like the rest of the app)

- **Move**: pointer-down on a bar body → ghost bar follows with day snapping;
  drop → PATCH `{start_date, target_date}` (duration preserved), optimistic
  via the existing item-mutations idiom.
- **Resize**: 6px grab zones at bar edges (`cursor: ew-resize`) → stretch/
  shrink either edge; drop → PATCH the changed date; `target >= start`
  clamped client-side (server 409 is the backstop).
- **Parent auto-stretch**: committing a CHILD move/resize that exceeds the
  parent epic's [start, target] issues a SECOND PATCH stretching the epic to
  the union (only outward, never shrinking; skipped when the epic is
  date-less/derived). Both PATCHes are one toast on failure + rollback.
- **Tray drag-in**: drag an unscheduled item from the tray onto a row lane →
  schedules it (`start = drop day`, `target = start + 6d` leaves, `+ 20d`
  epics — defaults documented in the tray hint).
- **Link creation**: a small ○ handle appears at bar ends on hover;
  dragging from ○ to another bar draws a rubber-band and POSTs an item link
  (`blocks` from source→target; toast on the 409s). Existing `blocks` edges
  render as the current red chips PLUS an SVG overlay of elbow connectors
  between visible bars (toggleable in the page header).
- Plain click still opens the peek panel (click vs drag = 4px threshold).

## 3. Right-click context menu (reuse `components/ContextMenu.tsx`)

On an EPIC bar: **Fit to children** (shrink/expand the epic's dates to
exactly span its children — the user's flagship ask), **Bring children into
roadmap** (schedule date-less children inside the epic's span, stacked
week-by-week), Expand/Collapse children, Clear dates (back to tray), Open.
On a LEAF bar: Clear dates, Open, Flag/unflag. Disabled entries show the
reason as the existing ContextMenu hint.

## 4. Page chrome

- The SLQ filter bar stays (it already narrows bars + tray live).
- Header adds: zoom (day-width select: 6/9/14px), Today button (scrolls the
  today line into view), dependency-lines toggle, and the standard
  DisplayMenu is NOT used here (roadmap has its own knobs).
- Workspace-spanning roadmap is OUT of scope — this remains the project
  roadmap page (`/p/$key/roadmap`).

## 5. Permissions + guards

- Gestures are enabled only when the actor holds item.update on the project
  (usePermissions); otherwise the page stays the current read-only timeline.
- Date PATCHes don't touch states, so spec-61 guards never fire here; the
  409 (`target >= start`) path surfaces as a toast + rollback.

## 6. Tests

- Pure model tests (extend the existing roadmap-model coverage if present,
  else add): bounds/fit-to-children math, clamp, derived epic spans,
  drag-day snapping math (`dayFromX` round-trips).
- Server is untouched — no new backend tests.

## Known simplifications

- Auto-stretch is client-orchestrated (two PATCHes, not a transaction): a
  failure mid-pair rolls both back optimistically and refetches — the server
  state is still valid either way (an epic narrower than a child is legal).
- Dependency connectors draw only between BOTH-visible bars (filtered-out
  endpoints fall back to the red chip).
- No critical-path/scheduling engine — dates mean what users set.

## As-built notes

Frontend-only, as specced — no server or migration changes; every gesture
persists through the existing `PATCH /items/{id}` (`start_date`/`target_date`,
`flagged`) and `POST /items/{id}/links` endpoints.

**Model** (`components/roadmap/roadmap-model.ts`, still pure — no React, no
browser APIs; `tsc` is the check since the web app has no JS test runner and
none was added): grew `xFromDay`/`dayFromX` (floor = the cell containing x) /
`dayDeltaFromDx` (round = snapped drag delta) / `clampDay`, `moveSpan`
(duration-preserving) + `resizeSpan` (edge never crosses the other) over the
padded domain (`ROADMAP_DOMAIN_PAD_DAYS = 28` appended past the last bar),
`isoFromDay`/`shiftIso`/`todayIso` local-midnight ISO round-trips,
`epicStretchPatch` (outward-only union; null for date-less epics),
`bringChildrenPlan` (week-stacked, capped to the epic span), and a richer
`RoadmapRow`: `derived` (date-less epic drawing its children's union — dashed,
not draggable), `parentEpicId` (child rows), `childrenBounds` {minStart,
maxTarget} ISO union, `datelessChildren`, `scheduledChildCount`. A scheduled
epic now draws its OWN window (not the children union) so Fit-to-children and
auto-stretch are visible truths. Zoom = day width threaded everywhere
(`ROADMAP_ZOOM_LEVELS` 6/9/14 px; compact zoom halves week-tick density).

**Gestures** (`useBarDrag.ts` — one pointer-event state machine per timeline;
4px threshold separates click→peek from drag; pointer capture + a body-level
cursor/user-select pin during drags): bar-body MOVE (ghost bar + live
"Jul 7 → Jul 20" chip, original position left as a dim slab), 6px edge RESIZE
zones (bars ≥ 18px), ○-handle LINK drag (rubber band in the SVG overlay; drop
target resolved via `elementFromPoint` + `data-bar-item`; `blocks`
source→target; 409s toast). Commits PATCH only the changed date(s) through
`useRoadmapItemPatch` (`lib/item-mutations.ts`) — a sequential multi-PATCH
mutation that paints all patches optimistically on the project item caches and
rolls the WHOLE set back with one toast on failure. Parent auto-stretch rides
that unit: a child commit exceeding its parent epic's window appends the
epic's outward-only stretch PATCH (skipped for derived epics). Tray drag-in is
HTML5 DnD (the tray is a separate panel): drop day = start,
`ROADMAP_LEAF_SPAN_DAYS = 6` / `ROADMAP_EPIC_SPAN_DAYS = 20` for the target;
an empty timeline accepts drops too (start = today); defaults documented in
the tray hint line.

**Right-click** (`RoadmapContextMenu.tsx` over the generic `ContextMenu`,
which gained an optional `hint` rendered as the row's title attr): epic bars —
Fit to children (disabled + hint without scheduled children; also works on a
derived epic, giving it real dates), Bring children into roadmap (week-by-week
stacking inside the epic span), Expand/Collapse children, Clear dates
(disabled on derived epics), Open; leaf bars — Clear dates, Open, Flag/Unflag.

**Rows/chrome** (`RoadmapTimeline.tsx`, `routes/roadmap.tsx`,
`useRoadmapEditing.ts`): epics are expandable rows (chevron; collapsed ids
per-project in localStorage `roadmapCollapseStorageKey`), dependency elbow
connectors (`Connectors.tsx`, red like the chips, arrowheaded, both-visible
bars only — filtered-out endpoints keep the red chip; header toggle, default
on), zoom select + Today (centers the today line in the scroll pane) in the
header, SLQ bar untouched. Everything mutating is gated on
`usePermissions().project(project, Permission.itemUpdate)` — without it the
page renders exactly the old read-only timeline (no handles, no menu, no
draggable tray).

**Deviations from the letter of the spec**: domain padding is appended at the
END only (per the spec text), so the earliest bar can't be dragged before its
own week's Monday without a second gesture; rank PATCH mentioned in the
preamble ended up unused (rows order by start date, not rank).
