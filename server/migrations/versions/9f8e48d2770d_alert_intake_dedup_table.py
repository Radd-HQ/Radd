"""alert intake dedup table (spec 47)

Revision ID: 9f8e48d2770d
Revises: 313d9671a1d3

"""
from alembic import op
import sqlalchemy as sa


revision = '9f8e48d2770d'
down_revision = '313d9671a1d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'alert_items',
        sa.Column('fingerprint', sa.Text(), nullable=False),
        sa.Column('item_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['work_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('fingerprint'),
    )


def downgrade() -> None:
    op.drop_table('alert_items')
