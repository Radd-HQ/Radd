# Spec 81 — Epic container drag (roadmap)

User direction: "the epic should behave almost like a big container — all
children in the view should move along with the epic." Frontend-only, on top
of specs 77–79.

## 1. Behavior

- MOVING an epic bar (body drag) shifts the epic AND every LOADED, SCHEDULED
  child by the same snapped day delta — durations preserved, relative layout
  inside the container intact. Date-less (tray) children unaffected.
- RESIZING an epic does NOT move children (resize adjusts the container's own
  window; fit-to-children remains the way to re-derive it).
- **Alt-drag = move ONLY the epic bar** (extends spec 78's Alt semantics:
  Alt already skipped the dependency cascade; it now also skips the
  children — "just this bar", one consistent escape hatch).
- Dependency cascade (spec 78) runs over the WHOLE moved set: every shifted
  bar (epic + children) seeds the push-forward planner against a working copy
  of spans, deduped, shared 50-item cap; everything joins ONE optimistic
  multi-PATCH unit (single rollback + toast). Children of OTHER epics pushed
  by the cascade still get their parent-stretch patches (existing machinery).

## 2. Visuals

- During an epic body-drag, the child bars render translated by the live
  snapped delta (same ghost treatment as the epic — the whole container
  visibly slides); connectors involving the set follow.

## 3. Model

- Pure `epicMovePlan(rows, epicId, deltaDays)` in roadmap-model.ts →
  `{patches}` for epic + scheduled children (shiftIso both dates); the commit
  path composes it with the (now multi-seed) cascade planner. Derived epics
  stay non-draggable (unchanged).

## 4. Tests

- Pure: epicMovePlan shifts epic + scheduled children only; Alt path yields
  the single-bar plan; multi-seed cascade dedupes and respects the cap.
  (tsc is the JS check; keep every rule in the pure model.)

## Known simplifications

- "Children in the view" is literal: only LOADED children move (a
  project-scoped roadmap won't shift cross-project children it never loaded —
  the workspace-spanning roadmap is the full-container surface).

## Tray filter (follow-up)

The Unscheduled tray excludes done/canceled-category items — it is a "to be
planned" pool, not an inventory (previously every loaded date-less item
appeared regardless of state). Scheduled done/canceled items still draw on
the timeline: history and the progress tints depend on them. Filter lives in
`buildRoadmapModel`'s unscheduled selection.

## As-built notes

Frontend-only, as specced — all math stays pure in `roadmap-model.ts`
(`tsc -b` + `vite build` are the JS check, as in 77–79).

**Model** (`roadmap-model.ts`): `epicMovePlan(rows, epicId, deltaDays)` →
`{patches}` shifting the epic (first) + every loaded scheduled child
(`parentEpicId === epicId`) by `shiftIso(±delta)` on both dates; derived or
date-less epics and delta 0 yield an empty plan. The cascade planner became
MULTI-SEED: `cascadePlanMulti(rows, seeds: RoadmapMove[])` takes the gesture's
moved spans as the starting frontier against the working copy, dedupes seeds,
and NEVER re-pushes a seed (the container's relative layout is the user's
statement — a pre-existing violated edge INSIDE the moved set stays violated
rather than being "fixed" mid-gesture); fan-in max on cascaded items and
push-forward semantics are unchanged, and the 50 cap counts CASCADED items
only (`moved.size - seeds.size`). `cascadePlan(rows, movedId, newSpan)`
remains as the single-seed wrapper, so the plain-bar path is untouched.

**Commit** (`useRoadmapEditing.commitSpan`): the gesture MODE now arrives in
the commit modifiers (`CommitModifiers {alt, mode}` from `useBarDrag`) — a
BODY move of a non-derived epic without Alt composes `epicMovePlan` (delta =
`isoDaysBetween(item.start_date, committed start)`) + `cascadePlanMulti` over
the container seeds into ONE `useRoadmapItemPatch` unit. Toasts: the existing
"Rescheduled N dependent item(s)" covers cascaded pushes; the children get no
toast (part of the gesture); cap trip toasts "…only KEY and its children were
moved" and commits just the container. RESIZE of an epic and Alt-drop take
the pre-81 single-bar path (Alt now skips children AND cascade — the
Dependencies-toggle tooltip and surface doc comment were reworded).

**Visuals** (`RoadmapTimeline.tsx`): while an epic body-drag is live (and Alt
is not held — `BarDragState.alt` is now tracked LIVE from pointer events, so
pressing Alt mid-drag collapses the container to just the bar), each child of
the dragged epic renders its bar at `row indices + the epic ghost's effective
delta` (read off the epic's preview span, so a domain clamp applies to the
children too) with the full ghost treatment — ring, dim original-position
slab. The per-bar live date chip renders only on the dragged epic (one chip
per gesture, not one per child — deliberate noise reduction). Connectors read
committed model spans and lag the translated children until the drop commits
(noted in-code, accepted by the spec).

**Deviations from the letter of the spec**: none functional. The date chip
suppression on translated children and the live-Alt visual collapse are the
two judgment calls beyond the text (the spec only required Alt-at-drop
semantics); tray/date-less children and derived epics behave exactly as
specced (untouched/non-draggable).

## Polish addendum: bar presentation

Frontend-only presentation pass over the roadmap bars (user ask: thicker
bars carrying info, plus a visual container around an epic's children).

**Geometry constants** (`roadmap-model.ts`, the one source shared by bar
rows, the connector overlay, drag ghosts/slabs, and the container region —
all fixed px, independent of the day-width zoom): `ROADMAP_LEAF_BAR_H = 30`,
`ROADMAP_EPIC_BAR_H = 34`, `ROADMAP_ROW_PAD_Y = 5`, and the derived row
pitch `ROADMAP_ROW_H = 44` (`roadmapBarHeight(isEpic)` picks the bar
height). `RoadmapTimeline` threads `ROADMAP_ROW_H` into `Connectors` as
`rowHeight` and uses it for label cells, lanes, the rubber-band anchor, and
the tray drop lane, so elbow endpoints, resize edge zones (still inset-y-0
inside the bar), the ○ link handle, and click→peek all track the new pitch
automatically.

**In-bar info** (`ROADMAP_BAR_INFO_MIN_PX = 90`): bars at least that wide
draw a pointer-events-none info row inside — truncated title (text-xs;
dark `text-zinc-950` on the solid leaf category fills, `text-zinc-100` on
canceled-zinc leaves and on the translucent epic fills) with a right-aligned
`PriorityIcon` + `AssigneeAvatar` cluster (leaves back the cluster with a
`bg-zinc-950/25` pill for contrast on any category color; unassigned items
just show priority). Narrower bars render the title OUTSIDE, right of the
bar (`text-xs text-zinc-300`, pointer-events-none so it never blocks
gestures) in one flex trail shared with the red depends-on chip so the two
never overlap; the trail offset clears the hover ○ handle in edit mode. The
live drag ghost keeps its date chip unchanged.

**Narrow-bar interaction** (same pass, follow-up fix): short-duration items
(1 day at the 6-9px zooms) rendered as ~6-14px slivers whose 6px resize
zones swallowed the whole bar. Bars now render at least
`ROADMAP_BAR_MIN_PX = 28` wide — presentation only: logical dates are
untouched, and since drag commits compute from snapped pointer DELTAS
(never the rendered width) a clamped bar moves/resizes correctly.
Everything hanging off the right edge (trailing title/chips, ○ handle,
connector elbow sources, the rubber-band anchor, the container region box)
positions off the CLAMPED edge via `barRenderWidth`/`barRenderRightX`.
Bars under `ROADMAP_NARROW_BAR_PX = 48` rendered get adaptive hit zones:
each edge zone shrinks to `ROADMAP_RESIZE_EDGE_NARROW_PX = 4` inside and
extends `ROADMAP_RESIZE_EDGE_OUTSET_PX = 6` OUTSIDE the bar (invisible,
ew-resize cursor), guaranteeing ≥ 20px of clean body-move area; normal
bars keep the 6px inside zones (`ROADMAP_RESIZE_EDGE_PX`), and the old
"bars < 18px skip resize" gate is gone (the min width makes it moot).
Gesture classification is element-based (the zones own their pointerdown,
`useBarDrag.begin` stops propagation), so hit layout and classification
cannot disagree. The hover ○ link handle gained a 16px invisible hit box
(`ROADMAP_LINK_HANDLE_HIT_PX`) with the dot centered — starting at the
bar's clamped right edge on normal bars, pushed past the outside resize
zone on narrow ones — and the trailing flex trail shifts right accordingly
so label/chip/handle never overlap. (A vertical hover slop was considered
and skipped: the bar button's background IS the visual, so slop would need
an inner-wrapper restructure.)

**Progress tints + hover card + one-day minimum** (same polish thread,
follow-up): the bar min-width rule changed — a bar's rendered width now IS
its logical width (one day is the floor by construction), so short tasks are
no longer exaggerated; `ROADMAP_BAR_MIN_PX` dropped 28 → **10** and is purely
an absolute grab floor that engages only when dayWidth < 10 (the 6px compact
and 9px default zooms' one-day bars). The hit-zone treatment grew a third
tier for that: `barHitZones(renderWidth)` (pure, roadmap-model.ts) returns
`{insidePx, outsidePx}` — normal (≥ 48px: 6px inside), narrow (≥
`ROADMAP_TINY_BAR_PX` = 2·4px + `ROADMAP_BAR_MIN_BODY_PX` 16 = 24px: 4px
inside + 6px outside), tiny (< 24px: zones FULLY outside, 10px each side, so
even a 10px bar keeps its whole body as move area); the ○ handle and depends
chip shift right by `outsidePx`. The **outside trailing title label was
DELETED** — the hover card replaces it (and the bars' native `title` tooltip;
an `aria-label` keeps the accessible name). The red **depends-on chip was
KEPT**: it is the only remaining signal when the blocker's bar isn't on the
surface (filtered out) or connectors are toggled off — exactly the cases the
elbow lines + amber violation styling cannot cover — and with the title gone
it no longer crowds; it hangs alone off the clamped edge as before.
**Tints**: bars draw a left-anchored overlay band — leaves at
min(logged/estimate, 1) from the timelog batch (no estimate → no band;
overlogged → full band + a 2px red right edge), epics at done/total from the
spec-76 rollup batch (childless → none). Band color splits on the fill:
`bg-zinc-950/25` on the light category fills, `bg-white/15` on the dark ones
(epic translucent fills, canceled zinc). All fractions come from ONE pure
source (`leafBarProgress`/`epicBarProgress`/`rowBarProgress`,
roadmap-model.ts) shared by the band and the card. **Data**: the surface's
spec-78 timelog fetch WIDENED from epic-children-only to the union of every
loaded leaf row id + every epic's loaded children, via
`timelogBatchChunkedQuery` (lib/queries.ts — one queryFn fanning out
sequential ≤`TIMELOG_BATCH_MAX_ITEMS` POSTs and merging; same retry:false
quiet-degrade), no longer gated on canUpdate (tints are read UI); epic
fractions ride `useRollupBatch` (spec 76) over the epic row ids (an epic past
the 200-id cap renders untinted). Both use
`ROADMAP_PROGRESS_STALE_MS` (5 min), no polling; item/worklog mutations still
invalidate through query meta. **Hover card** (`RoadmapHoverCard.tsx`): after
a `ROADMAP_HOVER_CARD_DELAY_MS` (350ms) dwell on a bar — never while ANY
gesture state is live (move/resize/link rubber band, even the pre-threshold
pointerdown), and cancelled on leave/click/context-menu/pane-scroll — a
fixed, viewport-clamped, pointer-events-none card (z above the connectors)
shows key + 2-line title, StatePill, priority icon + label, assignee
avatar + name (or "Unassigned"), TeamBadge when set, start → target (derived
epics show the children union, marked "from children"), and the progress
line: leaves "Estimate X · Logged Y" (formatDuration + useDurationConfig,
"· over" when overlogged), epics "N of M children done" — each over a slim
track at the same fraction as the bar's tint. One shared component for both
bar kinds; below-the-bar placement flips above near the viewport bottom
(LinkPopover clamp idiom).

**Child-container region**: every EXPANDED epic with ≥ 1 scheduled child
row gets a translucent box (`rounded-lg border-zinc-700/40 bg-zinc-800/15`,
pointer-events-none) on the lowest layer — below gridlines/today line, bars,
and connectors — spanning horizontally the union of the epic and its child
rows and vertically from the epic row's top to the last child row's bottom.
Derived (dashed) epics get it too. During an epic container drag the box
translates by the same live snapped delta as the epic ghost and its
translated children, so the whole container slides as one; collapsed epics
draw no box (no child rows beneath).
