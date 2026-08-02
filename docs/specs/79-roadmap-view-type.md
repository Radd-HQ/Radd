# Spec 79 — Roadmap as a view type (+ tray filters, no Load-more)

Roadmap follow-up 3: the roadmap stops being a standalone project page and
becomes `ViewType.ROADMAP` — an ordinary saved view. That single move buys
everything the user asked for: an EDITABLE SLQ query, quick-filter chips,
sharing/ownership, workspace-SPANNING custom roadmaps, and multiple roadmaps
per scope. Plus two tray fixes: an epics-only filter and full listing (the
roadmap fetches ALL matching items — no Load-more).

## 1. Server

- `ViewType.ROADMAP = "roadmap"` — accepted everywhere views are validated;
  axes stored-but-ignored (the planning/queue precedent). `cycle_filter` and
  `wip_limits` are inapplicable-but-harmless (UI simply doesn't offer them).
- Seeded project views (spec 67 idiom): `defaults.seed_project_views` gains
  **Roadmap** (after Planning); backfill migration adds a Roadmap view to
  every existing project that lacks one (workspace-visible viewer, owner
  NULL — identical to the other seeds).
- Nothing else — sharing, counts, quick filters, SLQ validation are already
  view-type-agnostic.

## 2. Frontend — routes/view.tsx renders roadmap views

- `ViewType.roadmap` renders the spec-77/78 timeline components as the third
  renderer branch (RoadmapSurface extracted from routes/roadmap.tsx). The
  standalone `/p/$key/roadmap` page is DELETED; the route redirects to the
  project's first roadmap-type view (else project home); ProjectNav drops its
  Roadmap entry (the sidebar's view list carries it now, like Board/List).
- **Fetch-all**: roadmap views auto-fetch every page of the view query
  (sequential fetchNextPage until exhausted) — no Load-more; the SLQ
  query + quick filters are the narrowing tools. A subtle count line shows
  "N items" while pages stream in.
- View machinery inherited for free: the view's SLQ is editable via Edit
  view; quick-filter chips AND into the fetch exactly like other views; the
  ad-hoc SLQ bar keeps filtering the loaded set; sharing/ownership dialogs
  identical.
- **Workspace-spanning roadmaps** (project_id NULL): bars/tray span readable
  projects; gestures gate on the SAME canUpdate rule other view types use;
  link creation stays same-project (cross-project drop → the existing 409
  toast); auto-schedule works per epic (its own project's estimates batch).
  Collapse/zoom localStorage keys move from project-scoped to VIEW-scoped.
- ViewModal: Roadmap joins the type picker; axis/cycle-filter/WIP controls
  hidden for it (like planning hides axes).

## 3. Tray upgrades

- Header filter chips: **All | Epics** (epics-only shows unscheduled epics —
  the "populate the roadmap top-down" flow). Persisted per view in
  localStorage alongside zoom.
- The tray lists the FULL unscheduled set (falls out of fetch-all).

## 4. Tests

- Server: roadmap view CRUD accepted + seeded on project create + backfill
  idempotence (service-level, tests/test_views* or a new small file).
- Web: `tsc` (no JS runner); renderer branching is thin over the already-pure
  model.

## Known simplifications

- Fetch-all streams 200/page sequentially; a giant unfiltered workspace
  roadmap is naturally slow — the answer is the SLQ query, not pagination.
- Cross-project dependency LINES render only when both endpoints are loaded
  (existing rule); manual links remain same-project (server invariant).

## As-built notes

**Server** (exactly the spec — validation was already view-type-agnostic, so
only two files): `ViewType.ROADMAP = "roadmap"` in `views/types.py` (axes
stored-but-ignored falls out of the existing schemas/service — no conditional
validation exists per type) and `("Roadmap", ViewType.ROADMAP, None)` appended
after Planning in `views/defaults.DEFAULT_VIEW_DEFS` (seeded by the existing
`project.created` hook). Backfill migration **`d1f80c2eedc3`** (hand-written
data migration, the `62681dd4006c` idiom, chained from `6941ef0ddab2`): INSERT
a pristine Roadmap view (workspace_access viewer, owner NULL, empty query) for
every project with no roadmap-TYPE view; downgrade deletes only untouched
seeded rows. Tests: `tests/test_roadmap_views.py` (create/patch acceptance
incl. workspace-spanning + retype, seeded set = Board/List/Planning/Roadmap
with the seed-shape asserts, `seed_project_views` idempotence — the backfill
predicate) + the spec-67 seed test in `test_view_sharing.py` updated to the
four-view set; suite 776 green.

**RoadmapSurface** (`components/roadmap/RoadmapSurface.tsx`, extracted from
`routes/roadmap.tsx` which is now a thin redirect — first roadmap-type view,
else project home; route + `RoutePath.roadmap` kept for old links): props
`{view (id + query_string), project (null = workspace-spanning), items
(fetched/filtered by the caller), canUpdate (view.tsx's existing rule:
project perm when scoped, global otherwise), filtered}`. Everything from
77/78 moved intact — gestures, cascade, auto-schedule, link popover, zoom,
Today, dependency toggle, ±extension — plus the roadmap's own knobs render as
a slim toolbar row under the view header (roadmaps get NO DisplayMenu; the
SLQ row, quick-filter chips, ad-hoc SlqFilterBar, Edit view/sharing/delete
are the view page's own chrome). view.tsx mounts it with `key={view.id}` so
zoom/extension/collapse/tray state re-initialize per view; localStorage moved
project→VIEW scope (`roadmapCollapseStorageKey(viewId)`; zoom stays session
state as it always was). `useRoadmapItemPatch` re-keyed from the project item
caches to the view's paged `viewItems` cache (the `useUpdateItemInView`
idiom) — gestures paint the effectiveView's cache, so quick-filtered fetches
stay consistent; `useRoadmapEditing(view, model)` accordingly.

**view.tsx branch**: `isRoadmap` renders the surface INSTEAD of the empty-state
short-circuit (an empty roadmap still shows its tray + drop-enabled empty
lane) and outside the card-scale zoom wrapper. Fetch-all = a four-dep effect
(`isRoadmap && hasNextPage && !isFetchingNextPage → fetchNextPage()`); the
existing header count line streams with a trailing "…" while pages load;
Load-more footer suppressed for roadmaps only. SLA/rollup batches are gated
OFF for roadmaps (bars, not cards — no pointless batch over a full fetch).
TypeIcon: `GanttChartSquare` in view.tsx AND the sidebar's `ViewRowContent`
(roadmap views just appear in the normal view lists; the sidebar + ProjectNav
fixed Roadmap entries were dropped). ViewModal: "Roadmap (timeline)" option;
`axesApply` excludes it (axis pickers hidden; the cycle-filter field follows
axesApply so it hides too; WIP editing lives on board column headers — n/a).

**Tray** (`UnscheduledTray.tsx`): header chips **All | Epics** (epics-only =
`kind === epic`) under the count badge, persisted per view in
`roadmapTrayFilterStorageKey(viewId)` (new, `lib/constants.ts`); the count
badge and empty message follow the active chip. No truncation existed — the
full set falls out of fetch-all.

**Workspace-spanning**: verified project-null paths — storage keys are
view-scoped (no project id needed), permissions use the global rule,
`projectTimeloggingQuery` is skipped and the estimates batch is simply
ATTEMPTED (`retry: false`, quiet degrade — readable ids always come back,
estimate-less ones default to `ROADMAP_LEAF_SPAN_DAYS`), cross-project link
creation surfaces the existing 409 toast, keys carry project prefixes.

**Deviations from the letter of the plan**: the surface takes no `workspaceId`
prop (nothing inside needs it — SlqFilterBar stays page-side); zoom was
session state in 77/78 and stays session state (the spec's "collapse/zoom
keys move to view scope" applied to keys that exist — collapse did, zoom
never persisted), so only collapse + the new tray filter live in
localStorage; `useAddItemLink`/`useRemoveItemLink` keep their (ignored)
projectId parameter to avoid touching `DependenciesSection`.
