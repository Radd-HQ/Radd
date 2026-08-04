"""d832grpsubj: groups are grant subjects (RADD-832)

`global_role_grants` gains `group_id` beside user_id/team_id, and the
`one_subject` CHECK widens from exactly-one-of-two to exactly-one-of-three
(num_nonnulls) — a role granted to an AD group directly, with no team invented
to hold it. `access_grants` needs no schema change: its subject columns are
already polymorphic (subject_type + subject_id); GROUP is a new subject_type
value validated in the service.

The CHECK is written by hand: Alembic's autogenerate does not emit table-level
check constraints (the d791spacescope lesson).

Revision ID: d832grpsubj
Revises: d829groups
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'd832grpsubj'
down_revision = 'd829groups'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('global_role_grants', sa.Column('group_id', sa.Uuid(), nullable=True))
    op.create_index(
        op.f('ix_global_role_grants_group_id'), 'global_role_grants', ['group_id'], unique=False
    )
    op.create_foreign_key(
        op.f('fk_global_role_grants_group_id_groups'),
        'global_role_grants', 'groups', ['group_id'], ['id'], ondelete='CASCADE',
    )
    op.create_unique_constraint(
        op.f('uq_global_role_grants_role_id_group_id_project_id_space_id'),
        'global_role_grants', ['role_id', 'group_id', 'project_id', 'space_id'],
    )
    op.drop_constraint(
        op.f('ck_global_role_grants_one_subject'), 'global_role_grants', type_='check'
    )
    op.create_check_constraint(
        'ck_global_role_grants_one_subject',
        'global_role_grants',
        'num_nonnulls(user_id, team_id, group_id) = 1',
    )


def downgrade() -> None:
    # Group-subject rows have no two-subject representation — they are dropped,
    # which is a permission NARROWING (fails closed), never a widening.
    op.execute("DELETE FROM global_role_grants WHERE group_id IS NOT NULL")
    op.execute("DELETE FROM access_grants WHERE subject_type = 'group'")
    op.drop_constraint(
        op.f('ck_global_role_grants_one_subject'), 'global_role_grants', type_='check'
    )
    op.create_check_constraint(
        'ck_global_role_grants_one_subject',
        'global_role_grants',
        '(user_id IS NULL) <> (team_id IS NULL)',
    )
    op.drop_constraint(
        op.f('uq_global_role_grants_role_id_group_id_project_id_space_id'),
        'global_role_grants', type_='unique',
    )
    op.drop_constraint(
        op.f('fk_global_role_grants_group_id_groups'), 'global_role_grants', type_='foreignkey'
    )
    op.drop_index(op.f('ix_global_role_grants_group_id'), table_name='global_role_grants')
    op.drop_column('global_role_grants', 'group_id')
