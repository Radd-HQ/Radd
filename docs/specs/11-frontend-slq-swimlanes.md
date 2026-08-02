# Spec 11 — frontend: SLQ query editing + swimlane boards

Allowed paths: `web/` + frontend row in `docs/modules.md`. Builds against spec 10's frozen
contract (read it first): views carry `query` (SLQ text), `group_by`/`swimlane_by` axis tokens
(`state|assignee|priority|kind|team|cf.<key>`, cf = select-type registry fields), `query_string`
(`q=…` appended verbatim to GET /items), parse errors 422 `{detail, position}`.

## View editor (replaces the chip builder)

- `ViewModal` v2: name, board/list, shared toggle (unchanged gating), then a **query editor**:
  monospace textarea, debounced live validation via `GET /items?<scope>&q=<draft>&limit=1` —
  on 422 render the message and use `position` to mark the offending spot (e.g. caret line under
  the text); on success show a live match count ("42 items match"). Collapsible **syntax
  cheat-sheet** panel generated from a constants file mirroring spec 10's grammar (fields incl.
  the registry's custom field keys fetched live, operators, examples). Keep the old chip builder
  code deleted, not hidden.
- Axis pickers: "Columns" (`group_by`) and "Swimlanes" (`swimlane_by`, optional, must differ) —
  options: State, Assignee, Priority, Kind, Team + every select-type custom field ("Show",
  "Department", …) labeled by field name, token `cf.<key>`.

## Board with swimlanes

- `ViewBoard` v2: when `swimlane_by` is set render swimlane rows (sticky row header: bucket
  name + count, collapsible, collapsed state in localStorage) × columns from `group_by`; each
  cell holds the items matching both bucket values. Single items fetch per view (existing
  pattern); bucket client-side from item data: states via /states, priorities/kinds static,
  assignee/team from item refs, cf.<key> values from the registry's option list (+ always a
  trailing "None" bucket for items lacking a value). Columns consistent across all swimlanes;
  empty cells render slim. No DnD on custom views (unchanged limitation).
- List views: server order (ORDER BY) is already respected — remove any client-side re-sorting.

## Also

- The default project Board/List (non-view routes) stay as they are.
- Item list route `/p/$projectKey/list`: add an optional SLQ input bar (same editor component,
  compact) that filters the list via `q=` — this gives ad-hoc querying outside saved views.
- Update the frontend row in docs/modules.md.

Environment: npm PATH bootstrap `<scratchpad>/bin`;
Playwright at scratchpad/pw-browsers (harness patterns in scratchpad/e2e). Backend may still be
landing spec 10 when you start — build to the contract, verify live once `q=` responds (poll
/openapi.json for the `q` param). Seeded admin hussein@hjarrar.com / change-me; real data —
test entities prefixed SPEC11, and DELETE the views you create when done (views have a DELETE
API). Never touch port 8000's process; vite 5173 killed by exact PID; final `npm run build`
refreshes the :8000 bundle (desired). Commit `-- web docs/modules.md` only.

Done = zero TS errors + Playwright evidence: create a view via SLQ text with live match count;
a deliberate typo shows the positioned error; a board grouped by state with swimlanes by a
custom field ("Show") renders the matrix with correct counts incl. None buckets; ad-hoc SLQ bar
filters the list; ORDER BY reflected in list order. Screenshots. Report evidence + gaps.
