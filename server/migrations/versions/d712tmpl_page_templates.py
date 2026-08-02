"""page templates (RADD-712)

Revision ID: d712tmpl
Revises: d719watch
"""
from alembic import op
import sqlalchemy as sa

revision = "d712tmpl"
down_revision = "d719watch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        # NULL = usable in every space. Scoping by absence rather than a join
        # table: a template belongs to one space or to all, and there is no
        # third case for an association table to express.
        sa.Column("space_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["space_id"], ["page_spaces.id"],
            name=op.f("fk_page_templates_space_id_page_spaces"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_page_templates_created_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_templates")),
        sa.UniqueConstraint("name", name="uq_page_templates_name"),
    )


def downgrade() -> None:
    op.drop_table("page_templates")
