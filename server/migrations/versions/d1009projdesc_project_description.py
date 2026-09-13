"""RADD-1009: projects gain a description

A project could be created and never described: the row carried a key and a
name, and the browser had no way to change even the name after creation. The
column is plain text, NOT NULL with an empty default, so every existing row
reads as "" rather than forcing a nullable branch on every consumer.

The KEY stays immutable — item keys (`TD-1234`) derive from it.

Revision ID: d1009projdesc
Revises: h1124vcsid
"""

import sqlalchemy as sa
from alembic import op

revision = "d1009projdesc"
down_revision = "h1124vcsid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("projects", "description")
