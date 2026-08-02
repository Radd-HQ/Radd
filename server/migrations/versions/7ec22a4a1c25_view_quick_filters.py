"""view quick filters

Revision ID: 7ec22a4a1c25
Revises: 9a829dc79eef

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '7ec22a4a1c25'
down_revision = '9a829dc79eef'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (alembic's usual false-positive drop of ix_doc_pages_fts stripped — see PLAN §11)
    op.add_column(
        'views',
        sa.Column(
            'quick_filters',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='[]',  # existing rows: no chips
        ),
    )


def downgrade() -> None:
    op.drop_column('views', 'quick_filters')
