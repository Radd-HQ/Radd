"""inline anchored + resolvable comments (RADD-726)

Revision ID: d726inline
Revises: 802d80435ed9

All three columns are NULLABLE, and that is the compatibility story: every
comment that exists stays exactly what it is — a thread comment, unresolved —
with no backfill and no default to argue about.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d726inline"
down_revision = "802d80435ed9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("comments", sa.Column("anchor", postgresql.JSONB(), nullable=True))
    op.add_column("comments", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.add_column("comments", sa.Column("resolved_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_comments_resolved_by_users"), "comments", "users", ["resolved_by"], ["id"]
    )
    # The rail asks one question per page: which inline threads are still open.
    op.create_index(
        "ix_comments_unresolved_inline",
        "comments",
        ["entity_type", "entity_id"],
        unique=False,
        postgresql_where=sa.text("anchor IS NOT NULL AND resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_comments_unresolved_inline", table_name="comments")
    op.drop_constraint(op.f("fk_comments_resolved_by_users"), "comments", type_="foreignkey")
    op.drop_column("comments", "resolved_by")
    op.drop_column("comments", "resolved_at")
    op.drop_column("comments", "anchor")
