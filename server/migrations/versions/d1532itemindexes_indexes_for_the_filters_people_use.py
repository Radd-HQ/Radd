"""d1532itemindexes: indexes for the filters and sorts people actually use (RADD-1532)

Measured on the 501k-item seed (EXPLAIN ANALYZE, best of three, warm cache),
before → after, each of these was a sequential scan or a full sort:

    label filter                    20.9 ms → 0.72 ms
    recently updated, one project   71.6 ms → 0.03 ms
    recently created, one project   69.5 ms → 0.02 ms
    my items by last update         63.5 ms → 0.03 ms
    title contains a rare word     170.5 ms → 0.03 ms
    custom field equals             94.9 ms → 0.01 ms

Each is tolerable alone; under concurrent use they compete for a small pool.

Built CONCURRENTLY: an instance with real data keeps reading and writing while
they build (about 12 s in total on the seed). The trigram index is guarded on
the extension, as d123ledger guards its own.

Revision ID: d1532itemindexes
Revises: d1525keyrecord
Create Date: 2026-11-16
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "d1532itemindexes"
down_revision = "d1525keyrecord"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_INDEXES = (
    ("ix_item_labels_label_id", "item_labels (label_id)"),
    ("ix_work_items_project_updated", "work_items (project_id, updated_at DESC)"),
    ("ix_work_items_project_created", "work_items (project_id, created_at DESC)"),
    ("ix_work_items_assignee_updated", "work_items (assignee_id, updated_at DESC)"),
    ("ix_work_items_custom_fields", "work_items USING gin (custom_fields jsonb_path_ops)"),
)
_TRIGRAM = ("ix_work_items_title_trgm", "work_items USING gin (title gin_trgm_ops)")


def upgrade():
    has_trgm = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
    ).scalar()
    with op.get_context().autocommit_block():
        for name, target in _INDEXES:
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {target}")
        if has_trgm:
            name, target = _TRIGRAM
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {target}")
        else:
            logger.warning(
                "pg_trgm is not installed — `title ~` stays a sequential ILIKE. Install the "
                "extension and create ix_work_items_title_trgm by hand; no re-migration is needed."
            )


def downgrade():
    with op.get_context().autocommit_block():
        for name, _ in (*_INDEXES, _TRIGRAM):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
