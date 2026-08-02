"""roles as data, project_members, project_teams role_id

Creates the `roles` and `project_members` tables (spec 06), backfills the builtin
admin/member/viewer roles for every existing workspace, and converts
`project_teams.role` (ProjectRole string) to a `role_id` FK onto that workspace's
builtin role of the same key.

Revision ID: 1ff7bd16bac6
Revises: cb29f8c473c0

"""
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '1ff7bd16bac6'
down_revision = 'cb29f8c473c0'
branch_labels = None
depends_on = None

# Frozen snapshot of auth/types.py BUILTIN_ROLES at this revision — migrations must not
# import app code. (key, name, description, permissions, position)
BUILTIN_ROLES = (
    (
        'admin',
        'Admin',
        'Full control of the project, including settings, views, and internal comments.',
        [
            'project.manage', 'item.read', 'item.create', 'item.update',
            'comment.write', 'comment.read_internal', 'view.manage',
        ],
        0,
    ),
    (
        'member',
        'Member',
        'Day-to-day work: read, create, and update items; comment; manage views.',
        [
            'item.read', 'item.create', 'item.update',
            'comment.write', 'comment.read_internal', 'view.manage',
        ],
        1,
    ),
    (
        'viewer',
        'Viewer',
        "Read-only access to the project's items.",
        ['item.read'],
        2,
    ),
)


def upgrade() -> None:
    op.create_table(
        'roles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['workspace_id'], ['workspaces.id'],
            name=op.f('fk_roles_workspace_id_workspaces'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
        sa.UniqueConstraint('workspace_id', 'key', name=op.f('uq_roles_workspace_id_key')),
    )
    op.create_index(op.f('ix_roles_workspace_id'), 'roles', ['workspace_id'], unique=False)

    op.create_table(
        'project_members',
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ['project_id'], ['projects.id'],
            name=op.f('fk_project_members_project_id_projects'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_project_members_user_id_users'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['role_id'], ['roles.id'], name=op.f('fk_project_members_role_id_roles'),
        ),
        sa.PrimaryKeyConstraint('project_id', 'user_id', name=op.f('pk_project_members')),
    )

    # Backfill: every existing workspace gets the builtin roles.
    connection = op.get_bind()
    workspace_ids = connection.execute(sa.text('SELECT id FROM workspaces')).scalars().all()
    insert = sa.text(
        'INSERT INTO roles (id, workspace_id, key, name, description, permissions, '
        'is_builtin, position, created_at, updated_at) '
        'VALUES (:id, :workspace_id, :key, :name, :description, CAST(:permissions AS jsonb), '
        'true, :position, now(), now())'
    )
    for workspace_id in workspace_ids:
        for key, name, description, permissions, position in BUILTIN_ROLES:
            connection.execute(
                insert,
                {
                    'id': str(uuid.uuid4()),
                    'workspace_id': workspace_id,
                    'key': key,
                    'name': name,
                    'description': description,
                    'permissions': json.dumps(permissions),
                    'position': position,
                },
            )

    # project_teams.role (string) -> role_id FK onto the workspace's builtin role.
    op.add_column('project_teams', sa.Column('role_id', sa.Uuid(), nullable=True))
    connection.execute(
        sa.text(
            'UPDATE project_teams pt SET role_id = r.id '
            'FROM projects p, roles r '
            'WHERE p.id = pt.project_id AND r.workspace_id = p.workspace_id AND r.key = pt.role'
        )
    )
    op.alter_column('project_teams', 'role_id', nullable=False)
    op.create_foreign_key(
        op.f('fk_project_teams_role_id_roles'), 'project_teams', 'roles', ['role_id'], ['id']
    )
    op.drop_column('project_teams', 'role')


def downgrade() -> None:
    op.add_column(
        'project_teams', sa.Column('role', sa.String(length=20), nullable=True)
    )
    op.get_bind().execute(
        sa.text(
            'UPDATE project_teams pt SET role = r.key FROM roles r WHERE r.id = pt.role_id'
        )
    )
    op.alter_column('project_teams', 'role', nullable=False)
    op.drop_constraint(op.f('fk_project_teams_role_id_roles'), 'project_teams', type_='foreignkey')
    op.drop_column('project_teams', 'role_id')
    op.drop_table('project_members')
    op.drop_index(op.f('ix_roles_workspace_id'), table_name='roles')
    op.drop_table('roles')
