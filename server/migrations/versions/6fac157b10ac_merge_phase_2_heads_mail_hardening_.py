"""merge phase-2 heads: mail hardening + round-robin cursor

Revision ID: 6fac157b10ac
Revises: d1044mailhard, d1044rrcursor
Create Date: 2026-08-12 01:09:26.172683

"""
from alembic import op
import sqlalchemy as sa


revision = '6fac157b10ac'
down_revision = ('d1044mailhard', 'd1044rrcursor')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
