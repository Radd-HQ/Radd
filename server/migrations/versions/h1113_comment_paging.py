"""Index chronological parent comment windows (RADD-1113).

Revision ID: h1113commentpage
Revises: g1093ghost
"""
from alembic import op

revision = "h1113commentpage"
down_revision = "g1093ghost"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_comments_parent_order", "comments", ["entity_type", "entity_id", "created_at", "id"])
    op.drop_index("ix_comments_parent", table_name="comments")


def downgrade():
    op.create_index("ix_comments_parent", "comments", ["entity_type", "entity_id"])
    op.drop_index("ix_comments_parent_order", table_name="comments")
