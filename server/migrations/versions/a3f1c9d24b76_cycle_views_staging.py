"""cycle view axis + staging (draft) cycles: nullable cycle dates, views.cycle_filter (spec 23)

Revision ID: a3f1c9d24b76
Revises: b154d8429f77

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3f1c9d24b76'
down_revision = 'b154d8429f77'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Draft (staging) cycles: dates become optional — a dateless cycle derives
    # to CycleStatus.DRAFT (see cycles/types.cycle_status).
    op.alter_column('cycles', 'start_date', existing_type=sa.Date(), nullable=True)
    op.alter_column('cycles', 'end_date', existing_type=sa.Date(), nullable=True)
    # Optional cycle-name glob for the `cycle` view axis header set.
    op.add_column('views', sa.Column('cycle_filter', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('views', 'cycle_filter')
    # Reverting to NOT NULL assumes no draft cycles remain (dateless rows would
    # violate the constraint — schedule or delete them before downgrading).
    op.alter_column('cycles', 'end_date', existing_type=sa.Date(), nullable=False)
    op.alter_column('cycles', 'start_date', existing_type=sa.Date(), nullable=False)
