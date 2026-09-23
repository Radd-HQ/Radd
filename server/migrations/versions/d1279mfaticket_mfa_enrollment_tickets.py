"""RADD-1279: the enrolment ticket a login refused under `require_mfa` gets.

Single-use (used_at), short-lived (expires_at), hash-only — the credential that
opens TOTP setup/confirm for a person who holds no session.

Revision ID: d1279mfaticket
Revises: d1291cyclehome
"""
import sqlalchemy as sa
from alembic import op

revision = "d1279mfaticket"
down_revision = "d1291cyclehome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mfa_enrollment_tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mfa_enrollment_tickets_user_id", "mfa_enrollment_tickets", ["user_id"])


def downgrade() -> None:
    op.drop_table("mfa_enrollment_tickets")
