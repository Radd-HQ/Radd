"""public kb (spec 74)

Revision ID: 7a1827897d5c
Revises: 48979a48f5b6

"""
from alembic import op
import sqlalchemy as sa


revision = '7a1827897d5c'
down_revision = '48979a48f5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (stripped: autogenerate's known ix_doc_pages_fts false-positive drop —
    # the functional GIN index alembic can't introspect; see PLAN §11)
    op.add_column('doc_spaces', sa.Column('public', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    # (matching ix_doc_pages_fts re-create stripped from the downgrade too)
    op.drop_column('doc_spaces', 'public')
