"""RADD-1273: AI providers state their request preferences

`reasoning` (off for every existing row — Radd asks a thinking model not to
think unless an admin says otherwise) and `request_params` (an admin-supplied
JSON object merged last into every chat payload).

Revision ID: d1273aireason
Revises: d1269scripts
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1273aireason"
down_revision = "d1269scripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_providers",
        sa.Column("reasoning", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "ai_providers",
        sa.Column(
            "request_params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_providers", "request_params")
    op.drop_column("ai_providers", "reasoning")
