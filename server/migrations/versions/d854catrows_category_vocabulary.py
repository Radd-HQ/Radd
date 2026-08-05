"""d854catrows: categories become user-owned rows; state groups fold in (RADD-854)

The consolidation: ONE classification tier over states — `state_categories`
rows (name/colour/order are the operator's; `behaves_as` anchors each row to
one of the six fixed semantics). The six builtins are seeded as editable rows
whose keys coincide with the old enum values, so `states.category_key` is a
straight backfill from `states.category` and pre-854 API payloads stay valid.
`states.category` remains as the DERIVED-but-stored semantic column every
report/sweep/guard keeps reading.

State groups (`d852stategrp`, never released) are dropped — the tier they
approximated is this one.

Revision ID: d854catrows
Revises: d852stategrp
Create Date: 2026-08-05
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = 'd854catrows'
down_revision = 'd852stategrp'
branch_labels = None
depends_on = None

BUILTINS = (
    ("triage", "Triage"),
    ("backlog", "Backlog"),
    ("todo", "Todo"),
    ("in_progress", "In Progress"),
    ("done", "Done"),
    ("canceled", "Canceled"),
)


def upgrade() -> None:
    op.create_table(
        'state_categories',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('behaves_as', sa.String(length=20), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_state_categories')),
        sa.UniqueConstraint('key', name=op.f('uq_state_categories_key')),
        sa.UniqueConstraint('name', name=op.f('uq_state_categories_name')),
    )
    conn = op.get_bind()
    for position, (key, name) in enumerate(BUILTINS):
        conn.execute(
            sa.text(
                "INSERT INTO state_categories (id, key, name, position, behaves_as, is_builtin) "
                "VALUES (:id, :key, :name, :position, :behaves, true)"
            ).bindparams(
                sa.bindparam('id', uuid.uuid4()),
                sa.bindparam('key', key),
                sa.bindparam('name', name),
                sa.bindparam('position', position),
                sa.bindparam('behaves', key),
            )
        )
    op.add_column('states', sa.Column('category_key', sa.String(length=60), nullable=True))
    conn.execute(sa.text("UPDATE states SET category_key = category"))
    op.alter_column('states', 'category_key', nullable=False)
    op.create_foreign_key(
        op.f('fk_states_category_key_state_categories'),
        'states', 'state_categories', ['category_key'], ['key'],
    )
    # State groups fold into this tier (unreleased — no data to preserve).
    op.drop_constraint(op.f('fk_states_group_id_state_groups'), 'states', type_='foreignkey')
    op.drop_column('states', 'group_id')
    op.drop_table('state_groups')


def downgrade() -> None:
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
    op.drop_constraint(op.f('fk_states_category_key_state_categories'), 'states', type_='foreignkey')
    op.drop_column('states', 'category_key')
    op.drop_table('state_categories')
