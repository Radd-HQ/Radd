"""d791spacescope: a role grant can be scoped to a wiki space

A space is a scope the way a project is (RADD-791). `global_role_grants` gains a
second, typed scope column with its own FK — not a polymorphic
`(scope_type, scope_id)` pair, which could not carry one, and which would leave
grants behind pointing at deleted spaces.

The `one_scope` CHECK is written by hand: Alembic's autogenerate does not emit
table-level check constraints, so relying on it would have shipped the column
without the rule that makes it meaningful.

Everything else autogenerate proposed was DRIFT, not this change, and is
deliberately absent: `item_embeddings`/`page_embeddings` are runtime-managed
outside `Base.metadata` (spec 103), `acme_notes` belongs to the example plugin,
and the rest were index renames left over from the doc->page rename (RADD-701).
Letting any of it ride along would have dropped the semantic index on deploy.

Revision ID: 307a8b156894
Revises: f782ssorules
Create Date: 2026-08-03 21:53:54.011097
"""
from alembic import op
import sqlalchemy as sa

revision = '307a8b156894'
down_revision = 'f782ssorules'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('global_role_grants', sa.Column('space_id', sa.Uuid(), nullable=True))
    op.create_index(
        op.f('ix_global_role_grants_space_id'), 'global_role_grants', ['space_id'], unique=False
    )
    op.create_foreign_key(
        op.f('fk_global_role_grants_space_id_page_spaces'),
        'global_role_grants', 'page_spaces', ['space_id'], ['id'], ondelete='CASCADE',
    )
    # A grant has AT MOST one scope. Both set would be an unanswerable question
    # ("this role, on that project, but only in that space").
    op.create_check_constraint(
        'ck_global_role_grants_one_scope',
        'global_role_grants',
        'project_id IS NULL OR space_id IS NULL',
    )
    # The uniqueness key gains the new scope column, so the same role can be held
    # globally, on a project, AND on a space without colliding.
    op.drop_constraint(
        op.f('uq_global_role_grants_role_id_team_id_project_id'),
        'global_role_grants', type_='unique',
    )
    op.drop_constraint(
        op.f('uq_global_role_grants_role_id_user_id_project_id'),
        'global_role_grants', type_='unique',
    )
    op.create_unique_constraint(
        op.f('uq_global_role_grants_role_id_team_id_project_id_space_id'),
        'global_role_grants', ['role_id', 'team_id', 'project_id', 'space_id'],
    )
    op.create_unique_constraint(
        op.f('uq_global_role_grants_role_id_user_id_project_id_space_id'),
        'global_role_grants', ['role_id', 'user_id', 'project_id', 'space_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f('uq_global_role_grants_role_id_user_id_project_id_space_id'),
        'global_role_grants', type_='unique',
    )
    op.drop_constraint(
        op.f('uq_global_role_grants_role_id_team_id_project_id_space_id'),
        'global_role_grants', type_='unique',
    )
    op.create_unique_constraint(
        op.f('uq_global_role_grants_role_id_user_id_project_id'),
        'global_role_grants', ['role_id', 'user_id', 'project_id'],
    )
    op.create_unique_constraint(
        op.f('uq_global_role_grants_role_id_team_id_project_id'),
        'global_role_grants', ['role_id', 'team_id', 'project_id'],
    )
    op.drop_constraint('ck_global_role_grants_one_scope', 'global_role_grants', type_='check')
    op.drop_constraint(
        op.f('fk_global_role_grants_space_id_page_spaces'),
        'global_role_grants', type_='foreignkey',
    )
    op.drop_index(op.f('ix_global_role_grants_space_id'), table_name='global_role_grants')
    op.drop_column('global_role_grants', 'space_id')
