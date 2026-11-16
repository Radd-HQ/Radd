"""d1524eventxact: events carry their transaction; consumers walk (xact_id, id) (RADD-1524)

An event id is taken at flush, not at commit, so a cursor on `id` could pass
id 101 while the transaction holding id 100 was still open and never see its
event. Every row now carries the id of the transaction that wrote it, and a
consumer's cursor is the pair `(xact_id, id)` read below the oldest transaction
still in flight.

Existing rows take 0, below every real transaction id, so a consumer at
`(0, N)` continues exactly where its old `last_event_id = N` left it.

Revision ID: d1524eventxact
Revises: d1499svcauto
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "d1524eventxact"
down_revision = "d1499svcauto"
branch_labels = None
depends_on = None

# A literal, not an import: a migration keeps meaning the same thing after the model moves.
XACT_ID_DEFAULT = "(pg_current_xact_id()::text)::bigint"


def upgrade():
    # A constant default is a catalog-only change on PostgreSQL 11+: no table rewrite,
    # however many events there are. The live default replaces it for new rows.
    op.add_column(
        "events", sa.Column("xact_id", sa.BigInteger(), nullable=False, server_default="0")
    )
    op.alter_column("events", "xact_id", server_default=sa.text(XACT_ID_DEFAULT))
    op.add_column(
        "consumer_offsets",
        sa.Column("last_xact_id", sa.BigInteger(), nullable=False, server_default="0"),
    )
    # The ledger is the largest table on a real instance: build without blocking writers.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_events_xact_id_id ON events (xact_id, id)"
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_events_xact_id_id")
    op.drop_column("consumer_offsets", "last_xact_id")
    op.drop_column("events", "xact_id")
