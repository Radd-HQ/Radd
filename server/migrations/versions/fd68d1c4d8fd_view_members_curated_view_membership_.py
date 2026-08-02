"""view_members: curated view membership (roadmap wave)

Revision ID: fd68d1c4d8fd
Revises: d109cardlay
Create Date: 2026-07-31 23:11:14.709916

NOTE: autogenerate also proposed dropping the runtime-managed embeddings
tables (outside Base.metadata by design, spec 103), the acme-notes example
plugin's table, and several expression/partial indexes it cannot model —
all stripped; this migration is ONLY the view_members table.
"""
from alembic import op
import sqlalchemy as sa

revision = 'fd68d1c4d8fd'
down_revision = 'd109cardlay'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'view_members',
        sa.Column('view_id', sa.Uuid(), nullable=False),
        sa.Column('item_id', sa.Uuid(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('added_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['added_by'], ['users.id'],
            name=op.f('fk_view_members_added_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['item_id'], ['work_items.id'],
            name=op.f('fk_view_members_item_id_work_items'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['view_id'], ['views.id'],
            name=op.f('fk_view_members_view_id_views'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('view_id', 'item_id', name=op.f('pk_view_members')),
    )
    op.create_index(op.f('ix_view_members_item_id'), 'view_members', ['item_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_view_members_item_id'), table_name='view_members')
    op.drop_table('view_members')
