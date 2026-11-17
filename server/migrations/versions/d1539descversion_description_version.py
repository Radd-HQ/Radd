"""d1539descversion: a version counter on the item description (RADD-1539)

`work_items.description_version` counts description edits, so a client can say
which text its edit started from and be refused when someone else saved in
between. Existing rows start at 0; nothing is backfilled because nothing needs
their history — only whether the text moved since a reader fetched it.

Adding a column with a constant default is a catalog change in PostgreSQL 11+:
no table rewrite, even at 500k rows.

Revision ID: d1539descversion
Revises: d1538failures
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "d1539descversion"
down_revision = "d1538failures"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "work_items",
        sa.Column("description_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("work_items", "description_version")
