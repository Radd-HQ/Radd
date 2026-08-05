"""d855vieworder: per-view bucket order for columns and swimlanes (RADD-855)

Two nullable JSONB lists of bucket KEYS on views — loosely coupled like
card_layout: unknown/departed keys are ignored at render, unlisted buckets
append in natural order, so a renamed state or a new category degrades
instead of breaking. NULL = the axis's natural order (every existing view).

Revision ID: d855vieworder
Revises: d854catrows
Create Date: 2026-08-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = 'd855vieworder'
down_revision = 'd854catrows'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('views', sa.Column('column_order', JSONB(), nullable=True))
    op.add_column('views', sa.Column('swimlane_order', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('views', 'swimlane_order')
    op.drop_column('views', 'column_order')
