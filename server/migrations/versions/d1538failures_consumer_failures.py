"""d1538failures: events a consumer failed on are kept, retried and replayable (RADD-1538)

`consumer_failures` — one row per (consumer, event) whose handler raised. Until
now that was a log line and a lost notification, webhook, index update or
automation run. Created empty: nothing was recorded before, so there is nothing
to backfill.

Revision ID: d1538failures
Revises: d1537transitions
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "d1538failures"
down_revision = "d1537transitions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "consumer_failures",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("consumer", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("first_failed_at", sa.DateTime(), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("consumer", "event_id"),
    )
    op.create_index(
        "ix_consumer_failures_due", "consumer_failures", ["consumer", "status", "next_attempt_at"]
    )


def downgrade():
    op.drop_table("consumer_failures")
