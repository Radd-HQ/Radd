"""sessions carry view_as_user_id (RADD-836 U1)

"View as": while set, requests on the session resolve to this user READ-ONLY
(the method guard lives in auth/deps.py). Hand-trimmed from autogenerate,
which also wanted to drop the runtime-managed embeddings tables and the
example plugin's table — none of ours.

Revision ID: aff6111e24f7
Revises: c1bfec45331b
Create Date: 2026-08-04 19:23:26.306874

"""
from alembic import op
import sqlalchemy as sa

revision = 'aff6111e24f7'
down_revision = 'c1bfec45331b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('view_as_user_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_sessions_view_as_user_id_users'),
        'sessions',
        'users',
        ['view_as_user_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_sessions_view_as_user_id_users'), 'sessions', type_='foreignkey')
    op.drop_column('sessions', 'view_as_user_id')
