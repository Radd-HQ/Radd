"""work_items estimate_points (spec 70)

Revision ID: d8402cfe3773
Revises: 7b7fa7839f55

"""
from alembic import op
import sqlalchemy as sa


revision = 'd8402cfe3773'
down_revision = '7b7fa7839f55'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('work_items', sa.Column('estimate_points', sa.Numeric(precision=6, scale=1), nullable=True))


def downgrade() -> None:
    op.drop_column('work_items', 'estimate_points')
