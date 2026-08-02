"""work_items.flagged — first-class boolean flag, not a label (spec 24)

Revision ID: c7e2a1f4d9b8
Revises: a3f1c9d24b76

"""
from alembic import op
import sqlalchemy as sa


revision = 'c7e2a1f4d9b8'
down_revision = 'a3f1c9d24b76'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'work_items',
        sa.Column('flagged', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('work_items', 'flagged')
