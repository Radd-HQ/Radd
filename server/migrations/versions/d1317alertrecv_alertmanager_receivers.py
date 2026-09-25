"""RADD-1317: Alertmanager receivers become rows; alert_items records its receiver.

Revision ID: d1317alertrecv
Revises: d1329verdict
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1317alertrecv"
down_revision = "d1329verdict"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alertmanager_receivers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("token", sa.String(200), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "alert_items",
        sa.Column(
            "receiver_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alertmanager_receivers.id", ondelete="SET NULL"), nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("alert_items", "receiver_id")
    op.drop_table("alertmanager_receivers")
