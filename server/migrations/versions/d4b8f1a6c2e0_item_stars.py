"""item_stars — per-user personal star/favorite (spec 24)

Revision ID: d4b8f1a6c2e0
Revises: c7e2a1f4d9b8

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4b8f1a6c2e0'
down_revision = 'c7e2a1f4d9b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'item_stars',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('item_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], name=op.f('fk_item_stars_user_id_users'), ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['item_id'], ['work_items.id'], name=op.f('fk_item_stars_item_id_work_items'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('user_id', 'item_id', name=op.f('pk_item_stars')),
    )


def downgrade() -> None:
    op.drop_table('item_stars')
