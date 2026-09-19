"""RADD-1266: automation run history

One row per applying run of an automation, holding the dry run's report shape
as JSONB. Swept by the scheduler after `automation_run_retention_days`.

Revision ID: d1266autoruns
Revises: d1265autolegacy
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1266autoruns"
down_revision = "d1265autolegacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_node_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("item_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("actions_applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actions_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_runs_automation_id", "automation_runs", ["automation_id"])
    op.create_index("ix_automation_runs_status", "automation_runs", ["status"])
    op.create_index(
        "ix_automation_runs_automation_started", "automation_runs", ["automation_id", "started_at"]
    )
    op.create_index("ix_automation_runs_started_at", "automation_runs", ["started_at"])


def downgrade() -> None:
    op.drop_table("automation_runs")
