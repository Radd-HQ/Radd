"""RADD-1269: the scripts plugin

Scripts (with versions), the packages asked for in the managed interpreter,
and the interpreter's single state row.

Revision ID: d1269scripts
Revises: d1268autover
"""

import sqlalchemy as sa
from alembic import op

revision = "d1269scripts"
down_revision = "d1268autover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scripts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "script_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("script_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("script_id", "version"),
    )
    op.create_index("ix_script_versions_script_id", "script_versions", ["script_id"])
    op.create_table(
        "script_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("spec", sa.String(length=300), nullable=False),
        sa.Column("resolved_version", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("log", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "script_interpreter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("python_version", sa.String(length=20), nullable=False, server_default="3.12"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="missing"),
        sa.Column("resolved", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("log", sa.Text(), nullable=False, server_default=""),
        sa.Column("built_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("script_interpreter")
    op.drop_table("script_packages")
    op.drop_table("script_versions")
    op.drop_table("scripts")
