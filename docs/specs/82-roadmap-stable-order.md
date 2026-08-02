# Spec 82 — Roadmap stable row order (rank-based)

User decision (discussion): roadmap rows stop re-sorting by date on
every commit — rows are STABLE and user-owned, ordered by the existing GLOBAL
manual rank (spec 24; one "manual order" shared with lists, deliberately).
Date-ordering becomes an explicit, persistent action.

## 1. Row order = rank (stop sorting by date)

- `buildRoadmapModel` preserves the FETCH order (the server's default IS rank
  order; an explicit view ORDER BY yields that order instead) for top-level
  rows (epics + standalone interleaved) AND for children within an epic. The
  current date sorts in grouping/children/standalone are removed.
- Bars therefore only move HORIZONTALLY on date changes; a drag never
  reshuffles rows.

## 2. Vertical reorder (the "epic rank" ask, satisfied by global rank)

- Row LABELS (the left label column) become drag-to-reorder handles among
  SIBLINGS: children reorder within their epic; top-level rows (epics +
  standalone) reorder among themselves. Persisted via the existing
  `PATCH /items/{id}/rank {after_id|before_id}` (midpoint + rebalance —
  nothing new server-side), optimistic like ViewList's row reorder.
- Enabled only when the view is RANK-ORDERED (no explicit ORDER BY in its
  SLQ — the same `rankOrdered` rule list views use) and the actor can edit.
- Because rank is global, this reorder is visible in list views too — one
  manual order everywhere (explicit user decision).

## 3. "Order children by date" (persistent verb)

- Epic context menu gains **Order children by date**: sorts the epic's loaded
  children by (start_date, target_date, key — date-less last) and rewrites
  their ranks to match via a sequential after_id chain of rank PATCHes (one
  toast on failure, single invalidate at the end).
- **Auto-schedule children** appends the same rank chain for its computed
  order, so a freshly scheduled epic reads top-to-bottom by date — the
  "default date order at import" ask. After that, rows sit where put.

## 4. Tests

- Pure model: input order preserved (no date sorts); sibling-scope resolution
  for the reorder targets. (tsc is the JS check; server rank machinery is
  already covered by spec-24 tests.)

## Known simplifications

- Views with an explicit ORDER BY show that order and disable vertical
  reorder (same trade as lists).
- The date-order verb touches LOADED children only (fetch-all makes this the
  full set in practice).

## As-built notes

Frontend-only, as specced — the spec-24 rank PATCH is the whole persistence
story, and every new ordering rule is a pure export in `roadmap-model.ts`
(`tsc -b` + `vite build` are the JS check, as in 77–81).

**Model** (`roadmap-model.ts`): the three date sorts are GONE (`byStart` on
children and standalone, the `groups.sort` by start). Grouping is now ONE
pass over the input building `TopLevelEntry[]` (`{group: EpicGroup} |
{leaf: Item}`) — epics-with-drawable-spans and standalone scheduled leaves
interleave exactly as encountered, and `scheduledChildren`/`allChildren`
keep their fetch order within each epic; the rows loop walks that list, so
fetch order (server default = global rank; an explicit ORDER BY otherwise)
IS the row order and bars only ever move horizontally. Domain math, the
derived-epic union, `childrenBounds`, and the tray (still `number` DESC,
done/canceled excluded) are untouched. New pure helpers:
`isRoadmapSibling(a, b)` (top-level rows — epic or standalone — are mutual
siblings; children are siblings within one epic),
`roadmapReorderNeighbours(rows, moved, target, before)` → the
adjacent-sibling `{afterId, beforeId}` computed with `moved` excluded (the
ViewList idiom; null for cross-scope drops — never a reparent),
`childrenDateOrder(children)` (start asc nulls-last, target asc same rule,
then numeric-aware key), and `RANK_CHAIN_MIN_ITEMS = 2`. `AutoSchedulePlan`
gained `orderedIds` — the schedule order, feeding the rank chain.

**Reorder gesture** (`RoadmapTimeline.tsx`): the row-label cell is an HTML5
drag handle (grab cursor, `effectAllowed = "move"`) when `canReorder` —
threaded as `canUpdate && rankOrdered` from `RoadmapSurface`, with
`rankOrdered` passed down from view.tsx's EXISTING regex rule (no explicit
`order by`, or `order by rank` — the same boolean the list's `onReorder`
gate uses). dragOver/drop engage only on SIBLING labels while a row drag is
live (`isRoadmapSibling`, self excluded) with stopPropagation so the tray's
body-level HTML5 drop never fires; tray drags don't set `rowDrag`, so the
two HTML5 drags can't cross wires. Indicator = the ViewList inset-shadow
line (top half = before, bottom = after) drawn across the WHOLE row; the
drop target is the label cell only (the lane keeps its gesture surface).
Commit (`useRoadmapEditing.reorderRow`): `roadmapReorderNeighbours` over
`model.rows`, then the UNCHANGED `useReorderItem(view)` — it was already
keyed to the paged `viewItems` cache (spec 24/55), the same key
`useRoadmapItemPatch` paints, so the optimistic flat-splice repaints the
roadmap rows instantly and rolls back on error. Ranks are global (explicit
spec-82 decision): a roadmap reorder is visible in rank-sorted lists too.

**Rank chain** (`useRoadmapEditing.applyRankChain`): sequential awaited
`PATCH /items/{id}/rank {after_id: prev, before_id: null}` — item[i] after
item[i-1], first item stays put; sequential because each PATCH anchors on
the previous item's FRESH rank. No epic anchor (ranks are global,
epics/children interleave). One error toast + stop on failure; ONE
`invalidateEntities(Entity.item)` in a `finally` either way; no optimistic
paint (the refetch snaps rows over). Note the server's after-only semantics
place the item at `after.rank + rank_step`, so a chain can leapfrog
unrelated global ranks — accepted; the drag gesture passes BOTH anchors and
gets the midpoint instead.

**Verb** (`RoadmapContextMenu.tsx`): **Order children by date**
(`CalendarArrowDown`) after Auto-schedule on epic rows —
`childrenDateOrder` then the chain, success toast "Ordered N children by
date"; disabled with the reason hinted when `!rankOrdered` (explicit ORDER
BY) or fewer than `RANK_CHAIN_MIN_ITEMS` loaded children.

**Auto-schedule** (`RoadmapSurface.handleAutoSchedule`): after the date
unit's `onSuccess` (optimistic multi-PATCH, unchanged), it fires
`applyRankChain(plan.orderedIds)` — chain failure toasts on its own and the
committed dates stand (deliberately NOT part of the optimistic unit).

**Judgment calls beyond the letter**: the auto-schedule chain is NOT gated
on `rankOrdered` (the spec text doesn't gate it; in an ORDER-BY view it
silently aligns the global rank other views use); the verb got a success
toast; the drop indicator spans the full row while the drop target stays
the label cell; child labels of COLLAPSED epics simply aren't rendered, so
they can't be reorder targets (expand first).

**"Bring children into roadmap" (follow-up)**: the epic context
menu regained an AS-IS import verb (`CalendarPlus`, placed ABOVE
Auto-schedule) — the no-reflow counterpart to spec 78's scheduler. Pure
`importChildrenPlan(children, epic, anchorIso, durations)` in
`roadmap-model.ts` returns `{patches, importedCount}`: already-dated children
are untouched; a missing start fills with the epic anchor (`epic.start ??
today` — the auto-scheduler's anchor rule; clamped back to the child's
existing target because the server 409s inverted spans); a missing target
fills with `start + duration − 1` (inclusive, anchored at the child's
effective start) where duration comes from the SAME source Auto-schedule
reads (timelog batch estimate + `useDurationConfig` hours/day via
`durationDaysFromEstimate`) and estimate-less children span
`ROADMAP_IMPORT_SPAN_DAYS = 1`; the epic fit patch (inward AND outward, over
every child's effective window) is appended last. One optimistic
`useRoadmapItemPatch` unit, toast "Brought N children into the roadmap" — NO
rank chain and no topo/assignee logic, so rows sit exactly where rank has
them. Disabled with the reason hinted: "No children loaded." / "All children
are already scheduled."

**Vertical bar-drag reorder (follow-up)**: the bar-BODY pointer
gesture (`useBarDrag`) is now AXIS-AWARE — at the existing 4px threshold the
dominant axis locks the gesture for its whole life: |dx| >= |dy| stays the
horizontal date move, a vertical win enters the new `BarDragMode.reorder`
(only when `canReorder` = `canUpdate && rankOrdered` is threaded in as
`reorderEnabled`; false = exactly the old horizontal-only behavior). Resize,
link, and tray gestures never re-classify, and Alt/cascade/container logic
stays horizontal-only. In reorder mode the bar holds its x (no ghost, no
date chip): the drag state carries the body-local pointer, and the pure
`rowDropFromY` helper (`roadmap-model.ts` — fixed `ROADMAP_ROW_H` pitch off
the row container's own rect; the axis header is a sibling, so no offset
math) maps it to the visible row half. ONE timeline resolver (sibling-only
via `isRoadmapSibling`, self excluded) feeds both the live indicator — the
SAME inset before/after line the label drag draws — and the drop, so they
can never disagree; the dragged row dims with a ring on its bar. A drop on
a valid sibling half calls the SAME `onReorderRow` → `reorderRow` rank-PATCH
path the labels use (optimistic, ViewList idiom); an invalid drop commits
nothing, and `consumeDragClick` still swallows the trailing click so the
peek panel stays shut. The label-drag handles keep working unchanged — two
routes to one rank write. Simplifications: no vertical auto-scroll in
reorder mode (the horizontal auto-scroll/extension rAF loop skips it), the
bar doesn't translate with the pointer (the indicator + dim carry the
feedback), and a derived epic's bar remains non-draggable as before — its
label is still its reorder handle.
