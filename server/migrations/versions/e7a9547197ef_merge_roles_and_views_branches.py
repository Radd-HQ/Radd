"""merge roles and views branches

Revision ID: e7a9547197ef
Revises: 0562875fb08a, 1ff7bd16bac6

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7a9547197ef'
down_revision = ('0562875fb08a', '1ff7bd16bac6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
