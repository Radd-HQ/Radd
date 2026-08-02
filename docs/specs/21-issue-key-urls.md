# Spec 21 — key-addressed issues: `/issues/TD-1234` (backend resolver + frontend rewrite)

Make the issue **key** (`PROJECT-NUMBER`, e.g. `TD-1234`) the canonical identity and URL, Jira-style.
Retire the `/p/{project}/{number}` issue-view scheme and the board's separate `/i/{number}`
side-panel URL. Numbering stays per-project (TD-1 and DEV-1 coexist).

Two parts: a small backend resolver (do inline / spec 21a) and a comprehensive frontend routing
rewrite (spec 21b, a frontend agent). "From the root, no shortcuts" — resolve by-key on the server;
do NOT keep the client-side number→id list-scan hack for the new route.

## 21a — Backend: by-key resolver (allowed paths: server/src/radd/modules/items/{service,router}.py, demo, docs)

- `items.service.get_item_by_key(session, key: str, actor) -> ItemRead`: parse `key` by the LAST
  `-` into (project_key, number) — project keys match `[A-Za-z][A-Za-z0-9]{0,9}` (no dashes), so
  `rsplit("-", 1)` is safe; number must be a positive int (else 404). Find project(s) whose key
  equals project_key (case-insensitive) that contain item #number; for each, `require(ITEM_READ)`
  and return the first the actor may read (single-workspace ⇒ unambiguous; document "first readable
  match wins" for the multi-workspace-duplicate-key edge). 404 (`NotFoundError(ItemEntity.ITEM, key)`)
  if none. Reuse the existing `hydrate`.
- Route `GET /api/v1/items/by-key/{key}` → `get_item_by_key` (distinct from `/items/{item_id}`:
  it's a 2-segment path; the `by-key` literal never collides with the UUID `{item_id}`). CurrentUser.
- The item's own `.id` is in the response, so all mutations (PATCH, links, comments) continue by id —
  only the initial resolution changes.
- Verify: `curl /items/by-key/TD-1` returns TD-1; a bad key / unknown → 404; a project the actor
  can't read → 404. Add a line to demo.sh (or a tiny check). pytest stays green.

## 21b — Frontend: unify on `/issues/{key}` (allowed paths: web/ + docs/modules.md)

- New route **`/issues/$itemKey`** (`RoutePath.issue = "/issues/$itemKey"`) under the app layout,
  component `ItemDetailPage`, resolving via `GET /items/by-key/$itemKey` (add `itemByKeyQuery` /
  `useItemByKey`) — replaces the current `useItemByNumber` list-scan. Keep reusing `ItemDetailBody`.
- **Retire** the old routes: remove `/p/$projectKey/issue/$number` (item-page) AND the nested
  board side-panel route `/p/$projectKey/i/$number` (`ItemDetailPanel`). Decision (matches Jira):
  clicking a **board card navigates to `/issues/$key`** (the full page) — the board no longer has a
  separate-URL side panel. Delete `ItemDetailPanel` and its route; keep `ItemDetailBody`,
  `useItemByNumber` may be deleted if now unused (check).
- **Repoint EVERY internal issue link** to `/issues/$key` (`params: { itemKey: item.key }`): list
  rows, board cards (`BoardCard`), roadmap bars, saved-view items (board + list rendering,
  `ViewSwimlanes`), the item detail's parent link + dependency links, the New-item modal's "created
  TD-x" link, and the form-submit success link. Grep for `RoutePath.item`, `RoutePath.issue` (old),
  `to={` with `number:` params, and `/p/$projectKey/i` — all must become `/issues/$key`.
- The issue page's back link: since it's no longer project-scoped in the URL, link back to the
  item's project board/list (the item carries `project_id`; resolve the project key from the loaded
  item) or to the projects index — keep a sensible back affordance.
- Display: keys already render as `TD-25` in most places; ensure the issue page title/header shows
  the key prominently and the browser tab/route reflects `TD-25`.
- `useCurrentWorkspace`/scope: the by-key endpoint resolves without a workspace in the URL, so no
  workspace needs to appear in issue URLs.

Environment: npm PATH `<scratchpad>/bin`;
Playwright at scratchpad/pw-browsers; backend live :8000 (the by-key endpoint will be live before the
frontend agent runs); seeded admin hussein@hjarrar.com / change-me. Never touch port 8000's
process; vite 5173 killed by exact PID; final `npm run build` refreshes the bundle. Commit
`-- web docs/modules.md` only.

Done = `npm run build` zero TS errors + Playwright: navigating to `/issues/TD-25` directly loads the
issue; clicking an issue from the LIST, the BOARD, and the ROADMAP all land on `/issues/TD-…`; a
parent/dependency link navigates by key; the old `/p/TD/issue/25` and `/p/TD/i/25` routes no longer
exist (404/redirect). Screenshot of `/issues/TD-25`. Report which links were repointed + any gaps.
