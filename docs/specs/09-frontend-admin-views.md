# Spec 09 — frontend: custom boards/views, admin panel, internal comments, permission gating

Allowed paths: `web/` + frontend row in `docs/modules.md`. Two phases (separate agents):

## Phase A (after specs 06 + 08 land): views + admin core

- **Views**: sidebar per-project section — Board, List, then saved views (shared + personal,
  personal marked). "New view" dialog: name, board/list, shared toggle (only when permitted),
  group_by picker, filter builder: multi-select chips for states, categories, kinds, priorities,
  assignees, teams, labels + custom-field value pickers generated from the field registry
  (select/multi_select fields only in v1). Views open at `/p/$projectKey/v/$viewId`: board honors
  group_by (columns = group values, incl. "Unassigned"/"No team" buckets) and preset filters
  (server-side via the documented filters→query-params mapping — no client-side filtering).
  Edit/delete from a view header menu. Workspace-level views (project_id null) appear in a
  sidebar "Views" section and render across projects.
- **Admin panel**: promote settings into an Admin area:
  - `/settings/roles`: role list (builtin badged, immutable), create/edit custom role with a
    permission checkbox matrix from `GET /permissions` (grouped by scope, with descriptions).
  - `/settings/members`: change workspace role, remove member (new PATCH/DELETE endpoints).
  - `/settings/projects` (new): per-project members (add user + role picker from `GET /roles`,
    change role, remove) and team attachments (attach/detach/change role).
  - `/settings/teams`: add the now-available detach/remove controls.
- **Permission gating**: replace `useIsWorkspaceAdmin` with `usePermissions()` fed by
  `ProjectRead.permissions` + `/auth/me` workspace permissions; gate New-item, view creation,
  settings affordances accordingly. Keep the 403 toast as backstop.

## Phase B (after spec 07 lands): field grants + internal comments

- `/settings/fields`: per-field "Permissions" editor — grant rows (role or team picker + read/write
  + remove), saved via `PUT /fields/{id}/permissions`; "x-restricted" fields badged in the table.
  Item detail: fields the user can't write render read-only; unreadable fields simply don't render
  (API already omits them).
- Comments: composer visibility toggle ("Public reply" / "Internal note", shown only with
  `comment.read_internal`), internal comments rendered with an amber Internal badge and distinct
  background. Comment counts already reflect visibility server-side.

Environment: npm bootstrap PATH `<scratchpad>/bin`;
backend on http://localhost:8000 (seeded admin hussein@hjarrar.com / change-me); Playwright in
scratchpad. `npm run build` zero TS errors + live Playwright verification of each deliverable
(screenshots). After build, run `npm run build` so the :8000 bundle refreshes. Vite on 5173 killed
by exact PID; never touch port 8000. Commit `-- web docs/modules.md` pathspecs only.
