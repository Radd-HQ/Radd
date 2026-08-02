# Spec 25 — Issue side panel + back-to-where-you-came-from

Two related navigation fixes (frontend-only).

## 1. Side panel (peek) — clicking an issue opens a drawer, not a new page

A `?peek=<itemKey>` search param on the shared pathless `appLayoutRoute`
(`validateSearch`, inherited by every in-app route) drives a right-side drawer
rendered once in `AppLayout` (`components/items/IssuePanel.tsx`).

- Clicking an issue (`usePeek().open(key)` in `hooks.ts`) does
  `navigate({ to: ".", search: prev => ({ ...prev, peek: key }) })` — it **stays
  on the current view** and only adds the search param, so the panel overlays
  the view. `to: "."` targets the current route (omitting `to` would target the
  root); the search param is inherited so it type-checks on every route.
- The panel reuses `ItemDetailBody` (via `useItemByKey`) behind a backdrop, with
  **Close** (×, or backdrop click, or Esc — unless typing in a field) and an
  **Open full page** (⤢) button that `expand`s to `/issues/$key` with
  `replace: true` (so Back from the full page returns to the clean view).
- Because it's a search param on the current route, the browser **Back button
  closes the panel** (returns to the view), and `?peek=…` URLs are shareable.
- Wired at every item-list surface: `BoardCard` (main board + view boards +
  swimlanes), `ViewList` rows, the ad-hoc project `ListPage` table, the **cycle
  page** rows, the **roadmap** bars + **UnscheduledTray**, and the **timesheet**
  issue rows. Still full-page (deliberately): the context-menu **Open** (explicit
  escalation), the form-submit success link, and parent/dependency links *inside*
  the detail body (panel-to-panel swap is a later polish).

## 2. Back button returns to where you came from

The full issue page (`item-page.tsx`) back control used a hardcoded `<Link>` to
the item's project board — so Back always went to the kanban board regardless of
origin. It now uses `useCanGoBack()` + `router.history.back()` (a real "Back"),
falling back to the project board / projects index only on a cold or shared load
with no in-app history.

## Notes / non-goals

- The old board side-panel route retired in spec 21 is **not** revived; this is a
  global search-param drawer over any view, not a nested route.
- Parent/dependency links inside the panel navigate to the full page rather than
  swapping the panel to the target issue (panel-to-panel swap is a later polish).
- The drawer uses a backdrop (modal-style); the view behind isn't interactive
  while it's open.
