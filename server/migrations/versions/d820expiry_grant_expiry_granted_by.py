"""d820expiry: grants carry expiry + granted-by (RADD-820)

Two nullable columns on both grant tables. NULL expiry = permanent (every
existing row — the migration changes nothing); NULL granted_by = pre-existing
or system-created, which is honest. Expiry applies at RESOLUTION time (the
liveness clauses); the hourly sweep only deletes corpses.

Revision ID: d820expiry
Revises: d819deny
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

revision = 'd820expiry'
down_revision = 'd819deny'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('access_grants', 'global_role_grants'):
        op.add_column(table, sa.Column('expires_at', sa.DateTime(), nullable=True))
        op.add_column(table, sa.Column('granted_by', sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f'fk_{table}_granted_by_users'),
            table, 'users', ['granted_by'], ['id'], ondelete='SET NULL',
        )


def downgrade() -> None:
    for table in ('access_grants', 'global_role_grants'):
        op.drop_constraint(op.f(f'fk_{table}_granted_by_users'), table, type_='foreignkey')
        op.drop_column(table, 'granted_by')
        op.drop_column(table, 'expires_at')
