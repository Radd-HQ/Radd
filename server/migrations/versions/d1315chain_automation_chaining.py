"""RADD-1315: automation chaining — the event records which automation caused
it and how deep in a chain; a trigger may opt in to other automations' changes.

Revision ID: d1315chain
Revises: d1314autokey
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1315chain"
down_revision = "d1314autokey"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("automation_rule_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("events", sa.Column("automation_depth", sa.SmallInteger(), server_default="0", nullable=False))
    op.add_column(
        "automation_triggers",
        sa.Column("include_automated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Existing automated rows predate depth; call them depth 1.
    op.execute("UPDATE events SET automation_depth = 1 WHERE automated")


def downgrade() -> None:
    op.drop_column("automation_triggers", "include_automated")
    op.drop_column("events", "automation_depth")
    op.drop_column("events", "automation_rule_id")
