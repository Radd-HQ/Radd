"""d1552countcover: a covering index for counts and per-state totals (RADD-1552)

`/items/count` for one project was a parallel sequential scan of the whole
table: `work_items` rows are wide, and no index held the columns the visibility
filter reads. Measured on the 501k-item seed, one project of 100,864:

    count                  95 ms  ->  10 ms
    count per state        (the board's column totals)  ->  14 ms

Partial on live rows, which is what every list, count and board reads. 44 MB at
501k items. Built CONCURRENTLY: an instance keeps writing while it builds.

Revision ID: d1552countcover
Revises: d1540relateditem
Create Date: 2026-11-17
"""

from alembic import op

revision = "d1552countcover"
down_revision = "d1540relateditem"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_work_items_project_state_cover "
            "ON work_items (project_id, state_id) "
            "INCLUDE (id, visibility, reporter_id, assignee_id, estimate_points) "
            "WHERE archived_at IS NULL"
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_work_items_project_state_cover")
