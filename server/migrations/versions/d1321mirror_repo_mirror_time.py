"""RADD-1321: the VCS time mirror is a per-repository switch, OFF by default.

It ran for every repository whose connection had an API token. The column is
added false for EVERY existing row too — including the one repository that was
mirroring on purpose, which is re-enabled by hand in Settings → Version control.

Revision ID: d1321mirror
Revises: d1319gchat
"""

import sqlalchemy as sa
from alembic import op

revision = "d1321mirror"
down_revision = "d1319gchat"
branch_labels = None
depends_on = None

TABLES = ("gitlab_repos", "github_repos", "forgejo_repos")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("mirror_time", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "mirror_time")
