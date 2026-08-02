"""field permission grants, comment visibility

Spec 07: creates `field_permissions` (per-role/team read|write grants), converts the
old `min_read_role`/`min_write_role` ladder columns into grants against each
workspace's builtin roles, drops those columns, and adds `comments.visibility`
(backfilled to 'public').

Conversion rules (default-open semantics — defaults produce NO rows):
- min_read_role: 'viewer' (default) -> none; 'member' -> read grants for the builtin
  admin + member roles; 'admin' -> read grant for the builtin admin role.
- min_write_role: 'member' (default) and 'viewer' (more open than open) -> none;
  'admin' -> write grant for the builtin admin role.

Revision ID: fa2747459c4b
Revises: e7a9547197ef

"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = 'fa2747459c4b'
down_revision = 'e7a9547197ef'
branch_labels = None
depends_on = None

# Frozen wire values at this revision — migrations must not import app code.
SUBJECT_ROLE = 'role'
ACCESS_READ = 'read'
ACCESS_WRITE = 'write'
# min-role value -> builtin role keys that receive a grant (empty = default-open).
READ_CONVERSION = {'viewer': (), 'member': ('admin', 'member'), 'admin': ('admin',)}
WRITE_CONVERSION = {'viewer': (), 'member': (), 'admin': ('admin',)}


def upgrade() -> None:
    op.create_table('field_permissions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('field_id', sa.Uuid(), nullable=False),
    sa.Column('subject_type', sa.String(length=10), nullable=False),
    sa.Column('subject_id', sa.Uuid(), nullable=False),
    sa.Column('access', sa.String(length=10), nullable=False),
    sa.ForeignKeyConstraint(['field_id'], ['field_definitions.id'], name=op.f('fk_field_permissions_field_id_field_definitions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_permissions')),
    sa.UniqueConstraint('field_id', 'subject_type', 'subject_id', 'access', name=op.f('uq_field_permissions_field_id_subject_type_subject_id_access'))
    )
    op.create_index(op.f('ix_field_permissions_field_id'), 'field_permissions', ['field_id'], unique=False)

    # Convert the ladder columns into grants against the workspace's builtin roles.
    connection = op.get_bind()
    fields = connection.execute(
        sa.text(
            'SELECT id, workspace_id, min_read_role, min_write_role FROM field_definitions'
        )
    ).all()
    builtin_roles = {
        (workspace_id, key): role_id
        for role_id, workspace_id, key in connection.execute(
            sa.text('SELECT id, workspace_id, key FROM roles WHERE is_builtin')
        ).all()
    }
    insert = sa.text(
        'INSERT INTO field_permissions (id, field_id, subject_type, subject_id, access) '
        'VALUES (:id, :field_id, :subject_type, :subject_id, :access)'
    )
    for field_id, workspace_id, min_read, min_write in fields:
        grants = [(role_key, ACCESS_READ) for role_key in READ_CONVERSION[min_read]]
        grants += [(role_key, ACCESS_WRITE) for role_key in WRITE_CONVERSION[min_write]]
        for role_key, access in grants:
            connection.execute(
                insert,
                {
                    'id': str(uuid.uuid4()),
                    'field_id': field_id,
                    'subject_type': SUBJECT_ROLE,
                    'subject_id': builtin_roles[(workspace_id, role_key)],
                    'access': access,
                },
            )

    op.drop_column('field_definitions', 'min_write_role')
    op.drop_column('field_definitions', 'min_read_role')

    # server_default backfills existing comments as public; the ORM sets values on insert.
    op.add_column(
        'comments',
        sa.Column('visibility', sa.String(length=10), nullable=False, server_default='public'),
    )


def downgrade() -> None:
    op.drop_column('comments', 'visibility')
    op.add_column('field_definitions', sa.Column('min_read_role', sa.VARCHAR(length=20), server_default=sa.text("'viewer'::character varying"), autoincrement=False, nullable=False))
    op.add_column('field_definitions', sa.Column('min_write_role', sa.VARCHAR(length=20), server_default=sa.text("'member'::character varying"), autoincrement=False, nullable=False))
    # Best-effort reconstruction of the ladder from builtin-role grants (custom-role and
    # team grants have no ladder equivalent and are dropped with the table).
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE field_definitions f SET min_read_role = "
            "  CASE WHEN EXISTS (SELECT 1 FROM field_permissions fp JOIN roles r ON r.id = fp.subject_id "
            "       WHERE fp.field_id = f.id AND fp.access = 'read' AND fp.subject_type = 'role' "
            "       AND r.is_builtin AND r.key = 'member') THEN 'member' ELSE 'admin' END "
            "WHERE EXISTS (SELECT 1 FROM field_permissions fp WHERE fp.field_id = f.id AND fp.access = 'read')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE field_definitions f SET min_write_role = 'admin' "
            "WHERE EXISTS (SELECT 1 FROM field_permissions fp WHERE fp.field_id = f.id AND fp.access = 'write')"
        )
    )
    op.drop_index(op.f('ix_field_permissions_field_id'), table_name='field_permissions')
    op.drop_table('field_permissions')
