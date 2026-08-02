"""page watchers (RADD-719)

Revision ID: d719watch
Revises: d726inline
"""
from alembic import op
import sqlalchemy as sa

revision = "d719watch"
down_revision = "d726inline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_watchers",
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_id"], ["pages.id"],
            name=op.f("fk_page_watchers_page_id_pages"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("page_id", "user_id", name=op.f("pk_page_watchers")),
    )
    # "what am I watching" — the profile-side read.
    op.create_index(op.f("ix_page_watchers_user_id"), "page_watchers", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_page_watchers_user_id"), table_name="page_watchers")
    op.drop_table("page_watchers")
