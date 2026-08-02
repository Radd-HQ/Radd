"""user preferences JSON (spec 94 — server-side per-user prefs)

Revision ID: f1a2b3c4d5e6
Revises: e53d08a57e29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f1a2b3c4d5e6"
down_revision = "e53d08a57e29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
