"""Preserve unknown imported comment authors without false attribution.

Revision ID: d1195commentauthor
Revises: d1175boardcols
"""
from alembic import op
import sqlalchemy as sa

revision = "d1195commentauthor"
down_revision = "d1175boardcols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("comments", "author_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    # Refuse when unknown authors exist rather than delete comments or invent authors.
    op.alter_column("comments", "author_id", existing_type=sa.Uuid(), nullable=False)
