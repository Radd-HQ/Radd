"""d1537transitions: item state/cycle history as a table the reports aggregate (RADD-1537)

`item_transitions` holds one row per item creation, state change and cycle
change. Until now every report rebuilt that per request from the event ledger.

The backfill is the same fold, run once in SQL over `item.created` /
`item.updated` events that carry a state snapshot (`payload->'item'->'state'`),
in event-id order — which is how the reports ordered them. Two corrections the
fold never made:

- an item with NO such event (seeded by SQL, or older than the RADD-922 payload
  shape) gets one row at its creation in the state it is in now, so it exists in
  a cumulative-flow chart. It is NOT marked as entering done: when it was
  finished is not known, and a throughput figure must not invent it;
- an item whose current state differs from the last one its events recorded
  (the source of a merge, whose tombstone is written without a snapshot) gets a
  row at its `updated_at` bringing the history up to the row.

Measured on a load database with 5.0M item events over 501k items: see the issue.

Revision ID: d1537transitions
Revises: d1533searchwindow
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "d1537transitions"
down_revision = "d1533searchwindow"
branch_labels = None
depends_on = None

_COLUMNS = (
    "item_id, project_id, at, state_id, category, cycle_id, state_changed, entered_done, "
    "stay_at, from_state_id, from_category, from_at, from_cycle_id"
)

_FOLD = f"""
INSERT INTO item_transitions ({_COLUMNS})
WITH snapshots AS (
    SELECT e.id, e.entity_id::uuid AS item_id, e.created_at AS at,
           (e.payload->'item'->'state'->>'id')::uuid AS state_id,
           e.payload->'item'->'state'->>'category' AS category,
           (e.payload->'item'->'cycle'->>'id')::uuid AS cycle_id
    FROM events e
    WHERE e.entity_type = 'item'
      AND e.event_type IN ('item.created', 'item.updated')
      AND e.payload->'item'->'state'->>'id' IS NOT NULL
      AND e.payload->'item'->'state'->>'category' IS NOT NULL
      AND e.entity_id ~ '^[0-9a-fA-F-]{{36}}$'
), sequenced AS (
    SELECT s.*,
           lag(state_id) OVER w AS previous_state,
           lag(category) OVER w AS previous_category,
           lag(cycle_id) OVER w AS previous_cycle,
           row_number() OVER w AS position
    FROM snapshots s
    WINDOW w AS (PARTITION BY item_id ORDER BY id)
), changes AS (
    SELECT *, (position = 1 OR state_id <> previous_state) AS state_changed
    FROM sequenced
    WHERE position = 1 OR state_id <> previous_state OR cycle_id IS DISTINCT FROM previous_cycle
), numbered AS (
    SELECT *, count(*) FILTER (WHERE state_changed)
                  OVER (PARTITION BY item_id ORDER BY id) AS stay
    FROM changes
), stays AS (
    SELECT *, first_value(at) OVER (PARTITION BY item_id, stay ORDER BY id) AS stay_at
    FROM numbered
), linked AS (
    SELECT *, lag(stay_at) OVER (PARTITION BY item_id ORDER BY id) AS previous_stay_at
    FROM stays
)
SELECT l.item_id, wi.project_id, l.at, l.state_id, l.category, l.cycle_id, l.state_changed,
       l.state_changed AND l.category = 'done'
           AND (l.position = 1 OR l.previous_category <> 'done'),
       l.stay_at,
       CASE WHEN l.state_changed THEN l.previous_state END,
       CASE WHEN l.state_changed THEN l.previous_category END,
       CASE WHEN l.state_changed THEN l.previous_stay_at END,
       l.previous_cycle
FROM linked l
JOIN work_items wi ON wi.id = l.item_id
ORDER BY l.id
"""

#: Items the fold produced nothing for: one row, at creation, in today's state.
_UNSEEN = f"""
INSERT INTO item_transitions ({_COLUMNS})
SELECT wi.id, wi.project_id, wi.created_at, wi.state_id, s.category, wi.cycle_id,
       true, false, wi.created_at, NULL, NULL, NULL, NULL
FROM work_items wi
JOIN states s ON s.id = wi.state_id
WHERE NOT EXISTS (SELECT 1 FROM item_transitions t WHERE t.item_id = wi.id)
"""

#: Items whose row has moved on from the last state their events recorded.
_CATCH_UP = f"""
INSERT INTO item_transitions ({_COLUMNS})
SELECT wi.id, wi.project_id, greatest(wi.updated_at, last.at), wi.state_id, s.category,
       wi.cycle_id, true,
       s.category = 'done' AND last.category <> 'done',
       greatest(wi.updated_at, last.at), last.state_id, last.category, last.stay_at, last.cycle_id
FROM work_items wi
JOIN states s ON s.id = wi.state_id
JOIN (
    -- Each item's newest row, in one pass: the indexes do not exist yet, and a
    -- per-item lookup here was a scan of the whole table for every item.
    SELECT DISTINCT ON (t.item_id) t.item_id, t.at, t.state_id, t.category, t.stay_at, t.cycle_id
    FROM item_transitions t ORDER BY t.item_id, t.id DESC
) last ON last.item_id = wi.id
WHERE last.state_id <> wi.state_id
"""


def upgrade():
    op.create_table(
        "item_transitions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "item_id", sa.Uuid(), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=True),
        sa.Column("state_changed", sa.Boolean(), nullable=False),
        sa.Column("entered_done", sa.Boolean(), nullable=False),
        sa.Column("stay_at", sa.DateTime(), nullable=False),
        sa.Column("from_state_id", sa.Uuid(), nullable=True),
        sa.Column("from_category", sa.String(length=20), nullable=True),
        sa.Column("from_at", sa.DateTime(), nullable=True),
        sa.Column("from_cycle_id", sa.Uuid(), nullable=True),
    )
    # Filled first, indexed after: building each index once over the finished
    # table is far cheaper than maintaining four through the insert.
    # The fold sorts every item event once per window; with the default 4 MB it
    # spills each sort to disk. Scoped to this transaction.
    op.execute("SET LOCAL work_mem = '256MB'")
    op.execute(_FOLD)
    op.execute(_UNSEEN)
    op.execute(_CATCH_UP)
    op.create_index("ix_item_transitions_project_at", "item_transitions", ["project_id", "at"])
    op.create_index("ix_item_transitions_item", "item_transitions", ["item_id", "id"])
    op.create_index(
        "ix_item_transitions_cycle", "item_transitions", ["cycle_id"],
        postgresql_where=sa.text("cycle_id IS NOT NULL"),
    )
    op.create_index(
        "ix_item_transitions_from_cycle", "item_transitions", ["from_cycle_id"],
        postgresql_where=sa.text("from_cycle_id IS NOT NULL"),
    )
    op.execute("ANALYZE item_transitions")


def downgrade():
    op.drop_table("item_transitions")
