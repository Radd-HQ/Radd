"""re-backfill work_items.rank newest-first so manual order = old created-desc default (spec 24)

Revision ID: f2b9d5e83a10
Revises: e6a0c3b19d47

"""
from alembic import op


revision = 'f2b9d5e83a10'
down_revision = 'e6a0c3b19d47'
branch_labels = None
depends_on = None

RANK_STEP = 1024.0


def upgrade() -> None:
    # Rank ascending is now the default list order (drag-to-reorder). Re-space so
    # newest = lowest rank = top, matching the previous created-desc appearance.
    op.execute(
        f"""
        UPDATE work_items AS w
        SET rank = seq.rn * {RANK_STEP}
        FROM (
            SELECT id, row_number() OVER (ORDER BY created_at DESC, id) AS rn
            FROM work_items
        ) AS seq
        WHERE w.id = seq.id
        """
    )


def downgrade() -> None:
    # Restore the original oldest-first spacing (migration e6a0c3b19d47).
    op.execute(
        f"""
        UPDATE work_items AS w
        SET rank = seq.rn * {RANK_STEP}
        FROM (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn
            FROM work_items
        ) AS seq
        WHERE w.id = seq.id
        """
    )
