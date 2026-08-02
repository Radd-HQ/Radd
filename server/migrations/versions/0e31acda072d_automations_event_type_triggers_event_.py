"""automations: event-type triggers + event conditions (spec 58)

Revision ID: 0e31acda072d
Revises: 5e4a41d09ca0

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0e31acda072d'
down_revision = '5e4a41d09ca0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automation_rules",
        sa.Column("event_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.alter_column(
        "automation_rules",
        "trigger",
        existing_type=sa.VARCHAR(length=20),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
    # Spec 58: triggers become raw event-type strings ("manual" stays as-is).
    op.execute("UPDATE automation_rules SET trigger = 'item.created' WHERE trigger = 'item_created'")
    op.execute("UPDATE automation_rules SET trigger = 'item.updated' WHERE trigger = 'item_updated'")


def downgrade() -> None:
    op.execute("UPDATE automation_rules SET trigger = 'item_created' WHERE trigger = 'item.created'")
    op.execute("UPDATE automation_rules SET trigger = 'item_updated' WHERE trigger = 'item.updated'")
    op.execute(
        "UPDATE automation_rules SET trigger = 'item_updated' "
        "WHERE trigger NOT IN ('item_created', 'item_updated', 'manual')"
    )
    op.alter_column(
        "automation_rules",
        "trigger",
        existing_type=sa.String(length=100),
        type_=sa.VARCHAR(length=20),
        existing_nullable=False,
    )
    op.drop_column("automation_rules", "event_conditions")
