"""csat surveys

Revision ID: d90a8f7daa8a
Revises: fb577d3807f9

"""
from alembic import op
import sqlalchemy as sa


revision = 'd90a8f7daa8a'
down_revision = 'fb577d3807f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: autogenerate also proposed dropping ix_doc_pages_fts (the expression
    # GIN index Alembic can't introspect) — stripped, as every migration since
    # the docs module has done.
    op.create_table('csat_surveys',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('rating', sa.SmallInteger(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('sent_at', sa.DateTime(), nullable=False),
    sa.Column('responded_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['work_items.id'], name=op.f('fk_csat_surveys_item_id_work_items'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_csat_surveys')),
    sa.UniqueConstraint('item_id', name=op.f('uq_csat_surveys_item_id')),
    sa.UniqueConstraint('token', name=op.f('uq_csat_surveys_token'))
    )


def downgrade() -> None:
    op.drop_table('csat_surveys')
