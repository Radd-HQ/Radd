"""view project defaults

Revision ID: 97f19379ae3c
Revises: 40573860b0bd

"""
from alembic import op
import sqlalchemy as sa


revision = '97f19379ae3c'
down_revision = '40573860b0bd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('views', sa.Column('project_default', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('views', 'project_default')
