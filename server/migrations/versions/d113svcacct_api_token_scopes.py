"""spec 113: per-key permission scopes

One nullable column. NULL means unscoped — every token that exists today keeps
carrying its account's full authority, which is exactly what it did before.

`UserSource.SERVICE` needs no migration: `users.source` is a string column, and
existing rows are untouched.

Revision ID: d113svcacct
Revises: d111fjconn
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d113svcacct"
down_revision = "d111fjconn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_tokens",
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_tokens", "scopes")
