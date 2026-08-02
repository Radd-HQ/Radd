# Spec 16 — reporting / dashboards (backend, Wave 2)

Read-only analytics computed from items + the event log + states + cycles. NO migration, NO new
tables (compute on the fly — acceptable at prototype scale; note it in modules.md). Depends on
spec 14 (cycles for velocity/burnup).

Allowed paths: `server/src/radd/modules/reporting/` (new), `server/src/radd/config.py` (modules
tuple), `server/tests/test_reporting.py` (new), `server/scripts/demo_reporting.sh` (new),
`docs/modules.md`. Since there's no migration, no head conflict with the parallel Wave-2 agents.
Never touch port 8000; verify on 8001/8002, kill exact PIDs. Explicit pathspec commits.

## Data source note

Time-in-state / throughput derive from the events outbox: `item.created` and `item.updated`
payloads carry the full item (incl. `state`), so state transitions are reconstructable by walking a
work item's events in order and diffing `state.category`/`state.id` between consecutive payloads.
Build a small helper `item_state_timeline(session, item_ids)` that returns, per item, the ordered
`(entered_at, state_id, category)` segments from its event history (bounded by the query window).

## Endpoints (all gated on `ITEM_READ` for the scope; project_id or workspace_id)

- `GET /reports/throughput?project_id=&start=&end=&interval=day|week` → buckets of items that
  ENTERED a `done`-category state in each bucket (from the timeline). `[{bucket, count}]`.
- `GET /reports/cumulative-flow?project_id=&start=&end=&interval=day|week` → per bucket, the count
  of items in each `StateCategory` at bucket end. `[{bucket, counts:{triage,…,done}}]`.
- `GET /reports/time-in-state?project_id=[&kind=]` → per state category, avg + median hours items
  spent there (completed segments only). `[{category, avg_hours, median_hours, sample}]`.
- `GET /reports/velocity?workspace_id=&last=N` → for the last N completed cycles, count of items
  completed (entered done while assigned to that cycle). `[{cycle:{id,name}, completed}]`.
- `GET /reports/burnup?cycle_id=` → daily series over the cycle window: scope (items in the cycle)
  vs completed. `{cycle, series:[{date, scope, completed}]}`.

Keep each report function small and pure where possible (compute over fetched rows). Guard windows
(reject start>end 422); default windows sensibly (throughput/CFD last 30 days).

## Verify (demo_reporting.sh, 8001)

Seed+login; create a project, a cycle, several items; move some to a done state (PATCH), assign
some to the cycle; call each endpoint and assert non-empty, well-formed shapes (e.g. throughput
bucket count matches the number moved to done; velocity lists the cycle; burnup series covers the
window). `uv run pytest` green (test the timeline helper + one report end-to-end against live DB in
a rolled-back txn, like the suggest tests); demo.sh/webhooks/permissions/views regression green.

Report: the endpoints, how the timeline reconstruction works, verification output, deviations, gaps
(e.g. cost of recomputing from events — fine for now, materialize later).
