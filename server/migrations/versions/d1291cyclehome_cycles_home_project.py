"""RADD-1291: a cycle has a home project.

`cycles.project_id` (nullable, SET NULL with the project) names who plans the
cycle. It is not a scope — a cycle still holds issues from any project.

Backfill: each cycle's home is the project holding the most of its issues right
now (ties broken by project id so the result is deterministic). A cycle with no
issues stays an instance cycle.

Revision ID: d1291cyclehome
Revises: d1290milestonesoff
"""
import sqlalchemy as sa
from alembic import op

revision = "d1291cyclehome"
down_revision = "d1290milestonesoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cycles", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_cycles_project_id_projects", "cycles", "projects",
                          ["project_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_cycles_project_id", "cycles", ["project_id"])
    op.execute("""
        UPDATE cycles AS c SET project_id = home.project_id
        FROM (
            SELECT DISTINCT ON (cycle_id) cycle_id, project_id
            FROM work_items
            WHERE cycle_id IS NOT NULL
            GROUP BY cycle_id, project_id
            ORDER BY cycle_id, count(*) DESC, project_id
        ) AS home
        WHERE c.id = home.cycle_id
    """)


def downgrade() -> None:
    op.drop_index("ix_cycles_project_id", table_name="cycles")
    op.drop_constraint("fk_cycles_project_id_projects", "cycles", type_="foreignkey")
    op.drop_column("cycles", "project_id")
