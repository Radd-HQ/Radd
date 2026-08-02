"""page_labels (RADD-718)

Revision ID: 3f09527aef0e
Revises: e1b95b0d2df1
Create Date: 2026-08-02 23:25:19.040073

Hand-trimmed for the same reason as e1b95b0d2df1: autogenerate proposes dropping
the runtime-managed embeddings tables (spec 103 keeps them out of Base.metadata
on purpose) and an example plugin's table on every run.
"""
from alembic import op
import sqlalchemy as sa

revision = '3f09527aef0e'
down_revision = 'e1b95b0d2df1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'page_labels',
        sa.Column('page_id', sa.Uuid(), nullable=False),
        sa.Column('label_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ['label_id'], ['labels.id'],
            name=op.f('fk_page_labels_label_id_labels'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['page_id'], ['pages.id'],
            name=op.f('fk_page_labels_page_id_pages'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('page_id', 'label_id', name=op.f('pk_page_labels')),
    )
    op.create_index(op.f('ix_page_labels_label_id'), 'page_labels', ['label_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_page_labels_label_id'), table_name='page_labels')
    op.drop_table('page_labels')
