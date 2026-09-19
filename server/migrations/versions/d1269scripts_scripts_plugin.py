"""RADD-1269: the scripts plugin

The packages asked for in the managed interpreter and the interpreter's
single state row. (A script library was here for a day and went with
RADD-1272 — the body lives on the automation node — before anything shipped,
so this migration was edited rather than followed by a drop.)

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
