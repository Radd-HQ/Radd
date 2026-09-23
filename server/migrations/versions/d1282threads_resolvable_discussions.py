"""RADD-1282: explicit resolvable discussions, preserving ordinary comments.

Revision ID: d1282threads
Revises: d1277scriptidx
"""
import sqlalchemy as sa
from alembic import op

revision = "d1282threads"
down_revision = "d1277scriptidx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("comments", sa.Column("is_thread", sa.Boolean(), server_default=sa.false(), nullable=False))
    # Inline annotations were always resolvable. Preserve any ordinary roots
    # explicitly resolved through the old API; replies never become blockers.
    op.execute("UPDATE comments SET is_thread = true WHERE parent_comment_id IS NULL AND ((anchor IS NOT NULL AND anchor != 'null'::jsonb) OR resolved_at IS NOT NULL)")
    op.create_index("ix_comments_unresolved_threads", "comments", ["entity_type", "entity_id"],
                    postgresql_where=sa.text("is_thread AND resolved_at IS NULL AND parent_comment_id IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_comments_unresolved_threads", table_name="comments")
    op.drop_column("comments", "is_thread")
