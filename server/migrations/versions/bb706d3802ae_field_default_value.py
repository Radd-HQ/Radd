"""field default_value

Revision ID: bb706d3802ae
Revises: f6cb41ece0f1

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'bb706d3802ae'
down_revision = 'f6cb41ece0f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ix_doc_pages_fts drop stripped — functional GIN index alembic can't introspect (false positive).
    op.add_column('field_definitions', sa.Column('default_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('field_definitions', 'default_value')
