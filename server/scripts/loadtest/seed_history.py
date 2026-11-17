"""Give a perf-seeded database an event history worth measuring (RADD-1536).

`perfseed.py` writes Jira-scale ROWS, but at most three events per item, and in
the pre-RADD-922 payload shape nothing reads any more. Everything that folds the
ledger — reports, item history, the audit log, SLA timers — has therefore only
ever run over a nearly empty stream. This writes about ten `item.created` /
`item.updated` events per item, in the shape `read._finish` emits
(`payload["item"]`, `payload["changes"]`), spread between the item's own
`created_at` and `updated_at`:

    default state ─▶ an in-progress state ─▶ the item's current state

with field edits between the moves, so a timeline has segments to fold and a
throughput report has done-entries in every week of the seed's eight years.

Only items with NO event are touched, so it is safe to re-run. It never has a
default target: `--db` is required, and it refuses the dev port unless asked.

    uv run python scripts/loadtest/seed_history.py --db postgresql://radd:radd@127.0.0.1:5458/radd
"""

from __future__ import annotations

import argparse
import sys
import time

import psycopg

DEV_PORT = 5455

#: Six to fourteen events an item, ten on average.
STEPS = "(6 + mod(abs(hashtext(wi.id::text)), 9))"

#: Where step n of an item's history sits: 0 = the project's default state,
#: 1 = an in-progress state, 2 = the state the item is in today. An item that
#: ended done/canceled passes through all three; one that merely left the
#: default goes straight there; one still in the default never moves.
PHASE = """CASE
    WHEN wi.state_id = ds.id THEN 0
    WHEN {n} >= k.steps - 1 THEN 2
    WHEN fs.category IN ('done', 'canceled') THEN
        CASE WHEN {n}::float / (k.steps - 1) < 0.25 THEN 0
             WHEN {n}::float / (k.steps - 1) < 0.80 THEN 1 ELSE 2 END
    WHEN {n}::float / (k.steps - 1) < 0.5 THEN 0
    ELSE 2 END"""

INSERT = f"""
INSERT INTO events (event_type, entity_type, entity_id, payload, created_at,
                    actor_id, silent, project_id, entity_label, search_text)
SELECT CASE WHEN g.n = 0 THEN 'item.created' ELSE 'item.updated' END,
       'item', wi.id::text,
       jsonb_build_object(
         'item', jsonb_build_object(
           'id', wi.id::text, 'key', p.key || '-' || wi.number, 'number', wi.number,
           'kind', wi.kind, 'title', wi.title, 'description', wi.description,
           'priority', wi.priority, 'flagged', wi.flagged, 'starred', false,
           'visibility', wi.visibility, 'project_id', wi.project_id::text,
           'project', jsonb_build_object('id', p.id::text, 'key', p.key, 'name', p.name),
           'state', jsonb_build_object('id', st.id::text, 'name', st.name,
                                       'category', st.category),
           'type', CASE WHEN it.id IS NULL THEN NULL ELSE jsonb_build_object(
               'id', it.id::text, 'name', it.name, 'color', it.color, 'icon', it.icon) END,
           'assignee', CASE WHEN au.id IS NULL THEN NULL ELSE jsonb_build_object(
               'id', au.id::text, 'name', au.name, 'avatar_url', NULL,
               'avatar_color', NULL, 'avatar_emoji', NULL) END,
           'reporter', CASE WHEN ru.id IS NULL THEN NULL ELSE jsonb_build_object(
               'id', ru.id::text, 'name', ru.name, 'avatar_url', NULL,
               'avatar_color', NULL, 'avatar_emoji', NULL) END,
           'cycle', CASE WHEN cy.id IS NULL OR ph.phase = 0 THEN NULL ELSE
               jsonb_build_object('id', cy.id::text, 'name', cy.name) END,
           'team', NULL, 'release', NULL, 'epic', NULL, 'parent', NULL,
           'links', jsonb_build_object('incoming', '[]'::jsonb, 'outgoing', '[]'::jsonb),
           'labels', '[]'::jsonb, 'past_cycles', '[]'::jsonb,
           'custom_fields', wi.custom_fields, 'estimate_points', wi.estimate_points,
           'start_date', wi.start_date, 'target_date', wi.target_date,
           'archived_at', NULL, 'child_count', 0, 'comment_count', 0,
           'epic_hidden', false, 'parent_hidden', false, 'capabilities', NULL,
           'email_signature', NULL,
           'created_at', to_jsonb(wi.created_at), 'updated_at', to_jsonb(ev.at)),
         'changes', CASE
           WHEN g.n = 0 THEN NULL
           WHEN ph.phase <> ph.previous THEN jsonb_build_array(jsonb_build_object(
               'field', 'state', 'from', pst.name, 'to', st.name))
           WHEN mod(g.n, 3) = 0 THEN jsonb_build_array(jsonb_build_object(
               'field', 'priority', 'from', 'normal', 'to', wi.priority))
           WHEN mod(g.n, 3) = 1 THEN jsonb_build_array(jsonb_build_object(
               'field', 'assignee', 'from', NULL, 'to', au.name))
           ELSE jsonb_build_array(jsonb_build_object(
               'field', 'description', 'from', '', 'to', left(wi.description, 200)))
         END) - CASE WHEN g.n = 0 THEN 'changes' ELSE '' END,
       ev.at,
       CASE WHEN g.n = 0 THEN wi.reporter_id ELSE coalesce(wi.assignee_id, wi.reporter_id) END,
       true, wi.project_id,
       left(p.key || '-' || wi.number || ' ' || wi.title, 300),
       p.key || '-' || wi.number || ' ' || wi.title
FROM work_items wi
JOIN projects p ON p.id = wi.project_id
JOIN states fs ON fs.id = wi.state_id
JOIN states ds ON ds.project_id = wi.project_id AND ds.is_default
JOIN LATERAL (SELECT {STEPS} AS steps) k ON true
JOIN LATERAL generate_series(0, k.steps - 1) g(n) ON true
JOIN LATERAL (SELECT {PHASE.format(n="g.n")} AS phase,
                     {PHASE.format(n="greatest(g.n - 1, 0)")} AS previous) ph ON true
JOIN LATERAL (SELECT wi.created_at
                     + (wi.updated_at - wi.created_at) * (g.n::float / (k.steps - 1)) AS at) ev ON true
LEFT JOIN LATERAL (SELECT s.id FROM states s
                   WHERE s.project_id = wi.project_id AND s.category = 'in_progress'
                   ORDER BY s.position LIMIT 1) mid ON true
JOIN states st ON st.id = CASE ph.phase WHEN 0 THEN ds.id WHEN 2 THEN fs.id
                                        ELSE coalesce(mid.id, ds.id) END
JOIN states pst ON pst.id = CASE ph.previous WHEN 0 THEN ds.id WHEN 2 THEN fs.id
                                             ELSE coalesce(mid.id, ds.id) END
LEFT JOIN issue_types it ON it.id = wi.type_id
LEFT JOIN users au ON au.id = wi.assignee_id
LEFT JOIN users ru ON ru.id = wi.reporter_id
LEFT JOIN cycles cy ON cy.id = wi.cycle_id
WHERE wi.project_id = %(project)s
  AND NOT EXISTS (SELECT 1 FROM events e
                  WHERE e.entity_type = 'item' AND e.entity_id = wi.id::text)
ORDER BY ev.at, wi.id, g.n
"""

#: Put the items a cycle's window covers INTO it, so velocity and burnup have
#: something to count: an item of the cycle's busiest project that was worked on
#: inside the window. Runs before the events are written; they carry the cycle.
ASSIGN_CYCLES = """
UPDATE work_items wi SET cycle_id = c.id
FROM cycles c
WHERE wi.cycle_id IS NULL
  AND c.start_date IS NOT NULL AND c.end_date IS NOT NULL
  AND wi.project_id = %(project)s
  AND wi.updated_at::date BETWEEN c.start_date AND c.end_date
  AND abs(hashtext(wi.id::text)) %% 4 = 0
"""


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", required=True, help="postgresql://… of the LOAD database")
    parser.add_argument("--allow-dev", action="store_true", help=f"allow port {DEV_PORT}")
    parser.add_argument("--cycle-project", help="project key whose items fill the cycles")
    args = parser.parse_args()

    with psycopg.connect(args.db) as conn:
        if conn.info.port == DEV_PORT and not args.allow_dev:
            sys.exit(f"refusing port {DEV_PORT} (the working database); pass --allow-dev to insist")
        cur = conn.cursor()
        cur.execute(
            "SELECT p.id, p.key, count(*) FROM work_items wi JOIN projects p ON p.id = wi.project_id "
            "GROUP BY p.id, p.key ORDER BY count(*) DESC"
        )
        projects = cur.fetchall()
        if args.cycle_project:
            target = next((pid for pid, key, _ in projects if key == args.cycle_project), None)
            if target is None:
                sys.exit(f"no project {args.cycle_project!r}")
            cur.execute(ASSIGN_CYCLES, {"project": target})
            log(f"{cur.rowcount:,} items of {args.cycle_project} placed in cycles")
            conn.commit()
        total = 0
        started = time.time()
        for index, (project_id, key, items) in enumerate(projects, 1):
            cur.execute(INSERT, {"project": project_id})
            total += cur.rowcount
            conn.commit()
            if cur.rowcount:
                log(f"{index}/{len(projects)} {key}: {items:,} items → {cur.rowcount:,} events "
                    f"({total:,} so far, {time.time() - started:.0f}s)")
        # No consumer may replay the synthetic backlog: every cursor jumps to the head.
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'consumer_offsets'")
        columns = {row[0] for row in cur.fetchall()}
        if "last_xact_id" in columns:
            cur.execute(
                "UPDATE consumer_offsets SET updated_at = now(), "
                "last_event_id = (SELECT max(id) FROM events), "
                "last_xact_id = (SELECT max(xact_id) FROM events)"
            )
        else:
            cur.execute("UPDATE consumer_offsets SET updated_at = now(), "
                        "last_event_id = (SELECT max(id) FROM events)")
        conn.commit()
        log(f"{total:,} events written; {cur.rowcount} consumer cursors moved to the head")
    with psycopg.connect(args.db, autocommit=True) as conn:
        conn.execute("ANALYZE events")
        conn.execute("ANALYZE work_items")
    log("analyzed")


if __name__ == "__main__":
    main()
