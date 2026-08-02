# Spec 18 — frontend: cycles, releases, item planning fields (Wave 3a, run FIRST)

Allowed paths: `web/` + frontend row in `docs/modules.md`. Runs SEQUENTIALLY before specs 19/20
(they share web/ files). Backend is LIVE on :8000 — build against real `/openapi.json`.

Contracts (verify against /openapi.json): `GET/POST/PATCH/DELETE /cycles?workspace_id=[&status=]`
(cycle: {id, name, start_date, end_date, goal, status: upcoming|active|completed}; create/edit needs
`cycle.manage` — held by workspace/instance admin); `GET/POST/PATCH/DELETE /releases?project_id=`
(release: {id, name, version, status: planned|released, released_at, description}; needs
`project.manage`); ItemRead now has `start_date`, `target_date`, `cycle {id,name,status}|null`,
`release {id,version,status}|null`, `links {outgoing:[{link_type,item:{id,key,title}}], incoming:[…]}`;
ItemUpdate accepts `start_date`, `target_date`, `cycle_id`, `release_id` (null clears);
`POST /items/{id}/links {target_number|target_id, link_type: blocks|relates|duplicates}` +
`DELETE /items/{id}/links/{link_id}`.

## Deliverables

1. **Item detail (both the panel and the full page — they share `ItemDetailBody`)**: add to the
   pickers grid — a **Cycle** select (`GET /cycles?workspace_id`, None + cycle names with a small
   status dot), a **Release** select (`GET /releases?project_id`, None + versions), and **Start /
   Target date** inputs (native date pickers, null-clears). Add a **Dependencies** section: list
   outgoing + incoming links grouped by type ("Blocks", "Blocked by", "Relates to", "Duplicates"),
   each a link to that item's page + a remove (×); an "add link" row (type select + item-key/number
   input, POST). Optimistic where reasonable; 409s surfaced inline.
2. **Cycles**: sidebar workspace section "Cycles" listing cycles (active one badged); a cycle page
   `/cycles/$cycleId` showing its items (fetch `GET /items?` with `cycle_id` if the backend filters
   by it, else client-filter by `item.cycle?.id`) grouped by state, with the cycle's dates/goal and
   a small progress bar (done/total). `/settings/cycles` (or a modal from the sidebar): create/edit/
   delete cycles (name, start/end dates, goal), gated on `cycle.manage`.
3. **Releases**: `/settings/releases` per-project — list (version, status, released_at), create/edit
   (name, version, description), a "Mark released" action (PATCH status→released), delete. Gated on
   `project.manage`. Show an item's release as a small chip on cards/detail.
4. Extend `lib/types.ts` (Cycle, Release, ItemLink, planning fields on Item), `lib/queries.ts`
   (cyclesQuery, releasesQuery, item-links), `lib/constants.ts` (routes + api paths), sidebar,
   and the New-item modal (optional cycle/release/dates).

Environment: npm PATH `<scratchpad>/bin`;
Playwright at scratchpad/pw-browsers; seeded admin hussein@hjarrar.com / change-me (is instance
admin → holds cycle.manage). Create test entities prefixed SPEC18 and delete cycles/releases you
create (both have DELETE). Never touch port 8000's process; vite 5173 killed by exact PID; final
`npm run build` refreshes the :8000 bundle. Commit `-- web docs/modules.md` pathspecs only, message
ends `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

Done = `npm run build` zero TS errors + Playwright evidence: assign an item to a cycle + release +
dates from the issue page (API-confirmed), add a "blocks" link (API-confirmed, both ends shown),
create a cycle and see items on its page, create + mark-released a release. Screenshots. Report.
