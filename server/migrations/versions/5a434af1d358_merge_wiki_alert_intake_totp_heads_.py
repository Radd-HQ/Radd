"""merge wiki + alert intake + totp heads (specs 43/47/48)

Revision ID: 5a434af1d358
Revises: 7965c326d924, 9f8e48d2770d, a48b1c07totp

"""
from alembic import op
import sqlalchemy as sa


revision = '5a434af1d358'
down_revision = ('7965c326d924', '9f8e48d2770d', 'a48b1c07totp')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
