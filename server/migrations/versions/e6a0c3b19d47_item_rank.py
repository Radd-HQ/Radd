"""work_items.rank — manual sort key for drag-to-rank (spec 24)

Revision ID: e6a0c3b19d47
Revises: d4b8f1a6c2e0

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6a0c3b19d47'
down_revision = 'd4b8f1a6c2e0'
branch_labels = None
depends_on = None

# Mirror settings.item_rank_step so existing rows get a spaced initial order.
RANK_STEP = 1024.0


def upgrade() -> None:
    op.add_column(
        'work_items',
        sa.Column('rank', sa.Float(), nullable=False, server_default='0'),
    )
    # Backfill a distinct, spaced rank per item in creation order (global order).
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
    op.create_index(op.f('ix_work_items_rank'), 'work_items', ['rank'])


def downgrade() -> None:
    op.drop_index(op.f('ix_work_items_rank'), table_name='work_items')
    op.drop_column('work_items', 'rank')
