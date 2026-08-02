"""cycles completed_at

Revision ID: bda2d16f2533
Revises: 1ec5ca425fcd

"""
from alembic import op
import sqlalchemy as sa


revision = 'bda2d16f2533'
down_revision = '1ec5ca425fcd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (alembic's usual false-positive drop of ix_doc_pages_fts stripped — see PLAN §11)
    op.add_column('cycles', sa.Column('completed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('cycles', 'completed_at')
