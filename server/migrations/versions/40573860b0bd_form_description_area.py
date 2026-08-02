"""form description area

Revision ID: 40573860b0bd
Revises: d90a8f7daa8a

"""
from alembic import op
import sqlalchemy as sa


revision = '40573860b0bd'
down_revision = 'd90a8f7daa8a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('forms', sa.Column('description_enabled', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('forms', sa.Column('description_prompt', sa.String(length=200), server_default='Description', nullable=False))
    op.add_column('forms', sa.Column('description_required', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('forms', 'description_required')
    op.drop_column('forms', 'description_prompt')
    op.drop_column('forms', 'description_enabled')
