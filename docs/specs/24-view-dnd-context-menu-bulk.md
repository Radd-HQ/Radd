# Spec 24 — Saved-view interaction: drag-to-move, right-click menu, bulk, rank, star

Make saved views (list/board/swimlane) directly manipulable instead of read-only.
Five slices; **1–3 shipped** (frontend-only), **4–5 planned** (need backend).

## 1. Cross-bucket drag ✅

Dropping an item on a bucket sets the field the grouping axis represents:
backlog → cycle sets `cycle_id`, medium → high sets `priority`, a state column
sets `state_id`, etc. — optimistic, rolls back on error.

- `lib/axis-dnd.ts` (pure): `dragEnabledForAxis(axis, projectScoped)` and
  `bucketMovePlan(item, axis, bucket, ctx)` → `{ patch: ItemUpdate, optimistic:
  Partial<Item> }` or null (no-op / unsupported). Supported axes: `state` (project
  scope only — workspace-spanning state buckets are name-keyed, ambiguous),
  `priority`, `assignee`, `team`, `cycle`, and select `cf.<key>`. **`kind` is not
  draggable** (create-only, no conversion endpoint).
- `lib/item-mutations.ts` `useUpdateItemInView(view)`: PATCHes an item, merges the
  optimistic partial into the `viewItemsQuery` cache so it re-buckets instantly,
  reconciles with the server item on success, refetches on settle for true SLQ
  order, rolls back the list on error.
- Native HTML5 DnD (same mechanism as the main board — no new dep). Drop targets:
  `ViewList` sections, `ViewBoard` columns, `ViewSwimlanes` cells (a cell drop sets
  **both** the column and lane axis fields). Gated on `item.update` in scope; the
  view page (`routes/view.tsx`) owns the mutation, components own the drag DOM.

## 2. Right-click context menu + first-class `flagged` boolean ✅

`components/ContextMenu.tsx` — a generic positioned menu (flat actions,
separators, hover flyout submenus; closes on outside-click / Esc / scroll).
`components/items/ItemContextMenu.tsx` builds the item action tree: Open · Set
priority ▸ · Set state ▸ (project states) · Assign to me / Unassign · Move to
cycle ▸ (cycles + Backlog) · **Flag / Unflag** · Copy key · Copy link. Mutating
actions require `item.update` (else only Open/Copy show). Wired via `onContextMenu`
on list rows + board/swimlane cards. `lib/toast.ts` gains a `success` kind (Copy).

**Flag is a first-class boolean attribute, not a label hack** (revised): `work_items.flagged`
BOOLEAN NOT NULL default false, on `ItemCreate`/`ItemUpdate`/`ItemRead`; an SLQ
builtin field `flagged` (`= true | = false`, sortable, autocompletes true/false,
422 on other values); migration `c7e2a1f4d9b8`. The context menu / bulk / a
**flag toggle on the issue detail header** set the boolean; a `FlagBadge` (amber
flag) renders on cards, list rows, and the detail. Filter with SLQ `flagged = true`.
The per-user **star** (slice 5) is a separate concept.

## 3. Multi-select + bulk actions ✅ (list views)

`routes/view.tsx` owns a `Set<itemId>` selection; `ViewList` rows show a hover
checkbox (shift-click extends a range in render order, click toggles + anchors,
selection highlight). `components/views/BulkActionBar.tsx` floats when ≥1 selected:
Set priority · Move to cycle (incl. Backlog) · Assign to me · Flag (sets `flagged`
= true) · Clear — each fans out `useUpdateItemInView` PATCHes (skipping no-ops).
The "move a backlog into a sprint" tool. Gated on `item.update` in scope; list
views only.

## 4. Manual rank within a bucket ✅

Drag to hand-order items inside a section. `work_items.rank` DOUBLE (NOT NULL,
default 0), backfilled by creation order with `item_rank_step` (1024) spacing;
new items append to the bottom (`max(rank)+step`). `PATCH /items/{id}/rank
{after_id?, before_id?}` sets a **midpoint** between neighbours (top/bottom when a
neighbour is omitted), **rebalancing** (respace all by step) if the float gap
collapses; migration `e6a0c3b19d47`. `rank` is a **sort-only** SLQ field (`ORDER
BY rank`; no compare ops, excluded from filter-field autocomplete). **Rank is the
default list order** (revised): `GET /items` with no explicit `ORDER BY` now sorts
by `rank ASC` (was `created DESC`); rank is backfilled/assigned **newest-first**
(re-backfill migration `f2b9d5e83a10`, new items get `min(rank)-step`), so the
default *appearance* is unchanged but every list is reorderable. Frontend:
`useReorderItem(view)` (optimistic array splice); `ViewList` enables within-section
drag-to-reorder — with a top/bottom insertion indicator — whenever the view is
**rank-ordered** (no explicit non-rank `ORDER BY`) and the caller has `item.update`
— no SLQ typing required. Cross-section drag still changes the axis field (rank
preserved). Board/swimlane within-bucket reorder is deferred.

## 5. Personal star ✅

A per-user favourite, separate from the shared `flagged` boolean. `item_stars`
(user_id, item_id) owned by items; `PUT/DELETE /items/{id}/star` (idempotent,
`item.read`, no event — personal); `ItemRead.starred` is the requesting user's
star (hydration takes `actor_id`); SLQ `starred = true|false` (EXISTS over
item_stars for the current user); migration `d4b8f1a6c2e0`. Frontend: a
`StarButton` (hover-reveal, filled when starred) on list rows, a `StarBadge` on
board cards + the plain list, a Star/Unstar row in the context menu, and a star
toggle on the issue-detail header; `useToggleStar(view)` (optimistic) +
`useToggleStarOnItem()` (detail). Filter your favourites with SLQ `starred = true`.

## Non-goals / simplifications (slices 1–3)

- Multi-select is **list-view only** (boards/swimlanes select via drag/menu).
- Bulk fan-out is N PATCHes (N settle-invalidations) — fine at studio scale; a
  `POST /items/bulk` endpoint is a later optimization.
- Cross-bucket drag inherits the view's 200-item page cap; after a move the card
  keeps its array position until the settle refetch re-applies SLQ order.
- `cf.<key>` drop to the "None" bucket sends `custom_fields: {key: null}`; clearing
  depends on the registry accepting null for that field.
- The context menu and DnD live on **saved views**; the ad-hoc project list/board
  routes are unchanged (easy follow-up).
