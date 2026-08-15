"""TOTP recovery codes (RADD-677): single-use MFA fallback, hashes only.

Revision ID: f677recovery
Revises: e1086secbox
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f677recovery"
down_revision = "e1086secbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "totp_recovery_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_totp_recovery_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_totp_recovery_codes")),
    )
    op.create_index(
        op.f("ix_totp_recovery_codes_user_id"), "totp_recovery_codes", ["user_id"]
    )
    op.create_index(
        op.f("ix_totp_recovery_codes_code_hash"), "totp_recovery_codes", ["code_hash"]
    )


def downgrade() -> None:
    op.drop_table("totp_recovery_codes")
