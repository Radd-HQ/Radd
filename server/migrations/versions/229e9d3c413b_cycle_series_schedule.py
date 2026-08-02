"""cycle series schedule

Revision ID: 229e9d3c413b
Revises: 5df5c6f35ec7

"""
from alembic import op
import sqlalchemy as sa


revision = '229e9d3c413b'
down_revision = '5df5c6f35ec7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (alembic's usual false-positive drop of ix_doc_pages_fts stripped — see PLAN §11)
    op.add_column('cycle_series', sa.Column('start_weekday', sa.Integer(), nullable=True))
    op.add_column('cycle_series', sa.Column('duration_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('cycle_series', 'duration_days')
    op.drop_column('cycle_series', 'start_weekday')
