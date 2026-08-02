"""spec 111: CI state on a version-control link

The latest run for a ref, not a check-run history — three columns rather than a
table, because the panel answers "is this green" and nothing has asked for more.

Revision ID: d111ci
Revises: d113svcacct
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "d111ci"
down_revision = "d113svcacct"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "item_vcs_links",
        sa.Column("ci_state", sa.String(length=20), server_default="", nullable=False),
    )
    op.add_column(
        "item_vcs_links",
        sa.Column("ci_url", sa.String(length=2000), server_default="", nullable=False),
    )
    op.add_column("item_vcs_links", sa.Column("ci_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("item_vcs_links", "ci_updated_at")
    op.drop_column("item_vcs_links", "ci_url")
    op.drop_column("item_vcs_links", "ci_state")
