"""RADD-1277: the script interpreter's package index is an admin setting

`index_url` ("" = PyPI; an air-gapped site names its mirror) and `offline`
(resolve from the wheelhouses alone). Both on the one interpreter row.

Revision ID: d1277scriptidx
Revises: d1273aireason
"""

import sqlalchemy as sa
from alembic import op

revision = "d1277scriptidx"
down_revision = "d1273aireason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "script_interpreter",
        sa.Column("index_url", sa.String(length=500), server_default="", nullable=False),
    )
    op.add_column(
        "script_interpreter",
        sa.Column("offline", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("script_interpreter", "offline")
    op.drop_column("script_interpreter", "index_url")
