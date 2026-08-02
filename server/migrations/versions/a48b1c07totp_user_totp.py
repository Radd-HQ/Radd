"""user_totp — MFA enrollment for local-password accounts (spec 48)

Revision ID: a48b1c07totp
Revises: 313d9671a1d3

"""
import sqlalchemy as sa
from alembic import op

revision = 'a48b1c07totp'
down_revision = '313d9671a1d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_totp",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_totp")
