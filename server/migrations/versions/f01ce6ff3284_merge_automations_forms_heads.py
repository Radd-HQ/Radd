"""merge automations + forms heads

Revision ID: f01ce6ff3284
Revises: 48b0a4ae4291, d49968ce89b4

"""
from alembic import op
import sqlalchemy as sa


revision = 'f01ce6ff3284'
down_revision = ('48b0a4ae4291', 'd49968ce89b4')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
