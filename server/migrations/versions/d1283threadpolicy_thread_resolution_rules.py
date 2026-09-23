"""RADD-1283: who may resolve a thread, per project and per issue type.

No rows are seeded: no row means the default (the thread's author, plus
managers), which is exactly the rule RADD-1282 shipped with.

Revision ID: d1283threadpolicy
Revises: d1282threads
"""
import sqlalchemy as sa
from alembic import op

revision = "d1283threadpolicy"
down_revision = "d1282threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thread_resolution_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issue_type_id", sa.Uuid(), sa.ForeignKey("issue_types.id", ondelete="CASCADE"), nullable=True),
        sa.Column("resolvers", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "issue_type_id", name="uq_thread_resolution_rules_scope",
                            postgresql_nulls_not_distinct=True),
    )
    op.create_index("ix_thread_resolution_rules_project_id", "thread_resolution_rules", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_thread_resolution_rules_project_id", table_name="thread_resolution_rules")
    op.drop_table("thread_resolution_rules")
