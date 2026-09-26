"""RADD-1369: a repository's own switches — move merged issues to waiting for
release, and publish a released version — OFF for every row.

RADD-1309 deleted both behaviours (they ran for every repository with no
switch) in favour of automation templates; RADD-1369 brings them back as
per-repository settings. Existing rows start OFF like new ones: a repository
that should sweep on release (RADD's own GitHub repository) is switched on by
hand in Settings → Version control, as RADD-1321 did for time mirroring.

Revision ID: d1369vcspolicy
Revises: d1341liveplugin
"""

import sqlalchemy as sa
from alembic import op

revision = "d1369vcspolicy"
down_revision = "d1341liveplugin"
branch_labels = None
depends_on = None

TABLES = ("gitlab_repos", "github_repos", "forgejo_repos")
COLUMNS = ("move_on_merge", "publish_on_release")


def upgrade() -> None:
    for table in TABLES:
        for column in COLUMNS:
            op.add_column(table, sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table in TABLES:
        for column in COLUMNS:
            op.drop_column(table, column)
