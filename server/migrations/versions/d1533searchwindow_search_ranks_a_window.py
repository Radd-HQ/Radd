"""d1533searchwindow: an index for search's newest-matches window (RADD-1533)

Full-text search now ranks the newest N matches instead of every match. This
index is what makes "the newest N matches" cheap for a common word: the planner
walks recently updated rows and stops at N. Measured on the 501k-item seed, the
window query for a word matching 223k rows: 730 ms without it, 9 ms with it.

Revision ID: d1533searchwindow
Revises: d1532itemindexes
Create Date: 2026-11-16
"""

from alembic import op

revision = "d1533searchwindow"
down_revision = "d1532itemindexes"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_search_index_updated_at "
            "ON search_index (updated_at DESC)"
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_search_index_updated_at")
