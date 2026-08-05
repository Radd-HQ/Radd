"""d852stategrp: state groups — the presentation tier over states (RADD-852)

A user-defined grouping layer with NO semantics: the state keeps its fixed
category, so reports/sweeps/guards are untouched by whatever vocabulary an
instance invents. `states.group_id` is SET NULL on group delete — members
degrade to ungrouped, never block.

(Hand-written: the autogenerate at this head also swept in unrelated drift —
the runtime-managed embeddings tables, a plugin table, docs index renames.)

Revision ID: d852stategrp
Revises: d825flip
Create Date: 2026-08-05
"""
import sqlalchemy as sa
from alembic import op

revision = 'd852stategrp'
down_revision = 'd825flip'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'state_groups',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_state_groups')),
        sa.UniqueConstraint('name', name=op.f('uq_state_groups_name')),
    )
    op.add_column('states', sa.Column('group_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_states_group_id_state_groups'),
        'states', 'state_groups', ['group_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_states_group_id_state_groups'), 'states', type_='foreignkey')
    op.drop_column('states', 'group_id')
    op.drop_table('state_groups')
