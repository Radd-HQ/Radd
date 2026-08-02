# Spec 19 — frontend: roadmap/timeline/Gantt + reporting dashboards (Wave 3b, run AFTER 18)

Allowed paths: `web/` + frontend row in `docs/modules.md`. Runs SEQUENTIALLY after spec 18 lands
(shares web/ files — rebase on its committed state; item planning fields + cycle/release types
already exist in lib/types.ts). Backend LIVE on :8000 — build against real `/openapi.json`.

Reporting contracts: `GET /reports/throughput?project_id=&start=&end=&interval=day|week` →
`[{bucket,count}]`; `GET /reports/cumulative-flow?…` → `[{bucket,counts:{triage,…,done}}]`;
`GET /reports/time-in-state?project_id=[&kind=]` → `[{category,avg_hours,median_hours,sample}]`;
`GET /reports/velocity?workspace_id=&last=N` → `[{cycle:{id,name},completed}]`;
`GET /reports/burnup?cycle_id=` → `{cycle,series:[{date,scope,completed}]}`. Planning fields on
ItemRead (start_date/target_date/links) drive the roadmap.

## Deliverables

1. **Roadmap / timeline / Gantt** — a project view `/p/$projectKey/roadmap`: items with a
   `start_date`+`target_date` render as horizontal bars on a time axis (weeks/months), ordered by
   start; epics render as parent rows with their children grouped under them (use `kind`+`parent`);
   dependency links (`blocks`) draw as connectors or at least a "⛔ depends on TD-x" marker on the
   bar; items lacking dates list in an "Unscheduled" tray. Bars are clickable → issue page. Dragging
   to reschedule is OPTIONAL (nice-to-have; if you do it, PATCH start/target). Build the time axis
   and bar layout by hand (no chart lib needed) OR a tiny dependency-free SVG; keep files small.
   Sidebar per-project gets a "Roadmap" entry next to Board/List.
2. **Reporting dashboards** — `/p/$projectKey/reports` (project) and a workspace `/reports`
   (velocity): render each report. Draw charts as lightweight inline SVG (no heavy chart dependency
   — bars for throughput/velocity, stacked areas/bars for cumulative-flow, a burnup line pair
   scope-vs-completed, a table for time-in-state). Date-range + interval controls for throughput/CFD;
   a cycle picker for burnup; `last N` for velocity. Empty/loading states.
3. Types/queries/constants for the report shapes + routes; sidebar entries.

Keep any charting primitives in a small `components/charts/` (reusable SVG bar/line/stacked — each
tiny). No new heavy dependencies; if you must add one, justify it (prefer none).

Environment: npm PATH `<scratchpad>/bin`;
Playwright at scratchpad/pw-browsers; seeded admin hussein@hjarrar.com / change-me. The TD project
has 25 imported items (some with states) — good report fodder; set a couple of start/target dates
via API to populate the roadmap for your screenshot. Never touch port 8000's process; vite 5173
killed by exact PID; final `npm run build` refreshes the :8000 bundle. Commit `-- web docs/modules.md`
only, message ends `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

Done = `npm run build` zero TS errors + Playwright evidence: the roadmap renders dated items as bars
(+ an Unscheduled tray), the reports page renders throughput/CFD/time-in-state with real numbers,
velocity + burnup render for a cycle. Screenshots of the roadmap and the reports page. Report.
