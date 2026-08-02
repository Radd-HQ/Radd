# Spec 04 — web UI (React + TS), phases 1–3

Allowed paths: `web/` ONLY (plus your row in `docs/modules.md`). Backend contracts live in
specs 01–03 and the running server's `/openapi.json` (dev server on http://localhost:8000).
Some endpoints may not exist yet while backend waves run in parallel — build to the spec,
degrade gracefully (feature-detect via 404 → hide), and note it.

Stack (fixed): Vite + React 19 + TypeScript, TanStack Router + TanStack Query, Tailwind v4,
lucide-react icons. No heavy component library — small hand-rolled components in `web/src/components/`.
Keep files small (CLAUDE.md rules apply: enums/consts in `web/src/lib/`, no magic strings for
routes/query keys). `npm run build` must pass with zero TS errors; that plus manual
`npm run dev` checks are the verification bar.

API client: `web/src/lib/api.ts` — thin typed fetch wrapper, `credentials: "include"`,
base `/api/v1`, Vite dev proxy `/api → http://localhost:8000`. On 401 → redirect to /login.
Types in `web/src/lib/types.ts` mirroring the spec schemas (hand-written, keep in sync).

## Phase 1 (Wave 1): shell + auth + projects

- `/login`: email+password form → `POST /auth/login`, then `/`. Errors inline.
- App shell: left sidebar (workspace name, project list, settings link at bottom, user menu
  with logout), content area. Load `/auth/me` + `/workspaces` + `/projects` on boot;
  single-workspace assumption (use the first).
- `/` projects index: cards/rows (key, name), "New project" modal (key, name).
- Design: clean, dense, Linear-adjacent: dark-mode-first, keyboard focus states, system font stack.

## Phase 2 (Wave 2): board, list, item detail, create

- `/p/$projectKey` board: columns = `GET /states?project_id`, cards = `GET /items?project_id`
  grouped by `state.id`. Card: key, title, priority icon, labels chips, assignee initials,
  team badge, epic parent tag. Click → detail. Drag-and-drop between columns → PATCH state_id
  (optimistic via TanStack Query, rollback on error). Column header shows count.
- `/p/$projectKey/list`: table with filter bar (kind, state category, assignee, team, label).
- Item detail (route `/p/$projectKey/i/$number`, rendered as a right-side panel over board):
  title (inline edit), description textarea, state select, priority select, kind badge,
  parent link, assignee picker (`GET /users`), team picker (`GET /teams`), labels editor
  (free text chips), **custom fields form generated from `GET /fields?workspace_id`**
  (render by field type: select → dropdown, multi_select → chips, date → date input,
  number/text/url → inputs, boolean → toggle, duration → minutes input), comments thread
  (list + composer) via `/items/{id}/comments`.
- "New item" modal (from board + sidebar): title, kind, state, priority, assignee, team,
  parent (when kind != epic), labels, custom fields (required ones marked; 422 errors from
  the registry rendered per-field).
- Epics: board filter toggle (kind), and epic items show `child_count` progress.

## Phase 3 (Wave 3): settings + role-aware polish

- `/settings/fields`: list + create field definitions (key, name, type, options editor,
  required, min_read_role, min_write_role). `/settings/states` (per project: list, add, rename),
  `/settings/labels`, `/settings/teams` (create team, manage members, attach to project with role),
  `/settings/members` (workspace members + roles), `/settings/tokens` (PATs: create shows token
  once, list, revoke).
- Role-aware UI: hide create/edit affordances the current user lacks (infer from /auth/me
  instance/workspace role + 403 responses). 403 toast handler.
- Empty states + loading skeletons everywhere; keyboard: `c` = new item on board.

Commit per phase with only `web/` paths. Report with what routes exist and what was verified.
