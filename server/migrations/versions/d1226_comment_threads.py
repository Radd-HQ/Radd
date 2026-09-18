"""Persist replies to inline comment threads (RADD-1226)."""
from alembic import op
import sqlalchemy as sa

revision = "d1226threads"
down_revision = "d1214scale"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("comments", sa.Column("parent_comment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_comments_thread", "comments", "comments", ["parent_comment_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_comments_thread_order", "comments", ["parent_comment_id", "created_at", "id"])


def downgrade():
    op.drop_index("ix_comments_thread_order", table_name="comments")
    op.drop_constraint("fk_comments_thread", "comments", type_="foreignkey")
    op.drop_column("comments", "parent_comment_id")
