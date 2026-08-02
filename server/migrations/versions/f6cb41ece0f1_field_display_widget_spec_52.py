"""field display widget spec 52

Revision ID: f6cb41ece0f1
Revises: 643a19d63157

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6cb41ece0f1'
down_revision = '643a19d63157'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('field_definitions', sa.Column('display', sa.String(length=20), nullable=True))
    # NOTE: autogenerate's ix_doc_pages_fts drop is a false positive (functional GIN
    # index it can't introspect) — omitted on purpose.


def downgrade() -> None:
    op.drop_column('field_definitions', 'display')
