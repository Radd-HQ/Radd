"""d825flip: the Baseline narrows to item.read@own; Staff keeps existing accounts whole (RADD-825, Q2)

The deliberate act, per decision Q2: the release FLIPS the live Baseline row —
`item.read` becomes `item.read@own` and `page.read` leaves entirely (N5: a
floor page.read defeated every restricted space). Everything else on the row
(the Q4 author-own deletes, the F6 catalog reads, anything an admin added)
stays untouched.

Existing active accounts keep today's effective access: the migration seeds a
non-builtin **Staff** role holding exactly what left the floor (`item.read` +
`page.read`) and writes one instance-wide grant of it per existing active
human account (EMAIL- and SERVICE-source accounts excluded — the first never
held the Baseline, the second reads through its key's scopes). Per-user
grants, not a blanket: each is visible in the inspector, revocable one person
at a time, and NEW accounts created after the flip start at the narrow floor.

A fresh database skips all of it: no Baseline row yet (the seed writes the
new shape), no users to keep whole.

Revision ID: d825flip
Revises: d820expiry
Create Date: 2026-08-04
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = 'd825flip'
down_revision = 'd820expiry'
branch_labels = None
depends_on = None

STAFF_KEY = 'staff'
FLOOR_LEAVING = ('item.read', 'page.read')


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id, permissions FROM roles WHERE key = 'baseline'")
    ).first()
    if row is None:
        return  # fresh database: the seed writes the narrow shape directly

    permissions = [p for p in row.permissions if p not in FLOOR_LEAVING]
    if 'item.read@own' not in permissions:
        permissions.append('item.read@own')
    conn.execute(
        sa.text("UPDATE roles SET permissions = :perms WHERE id = :id").bindparams(
            sa.bindparam('perms', permissions, type_=sa.dialects.postgresql.JSONB),
            sa.bindparam('id', row.id),
        )
    )

    users = conn.execute(
        sa.text(
            "SELECT id FROM users WHERE active = true "
            "AND (source IS NULL OR source NOT IN ('service', 'email'))"
        )
    ).fetchall()
    if not users:
        return  # nobody predates the flip; nothing to keep whole

    staff_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO roles (id, key, name, description, permissions, is_builtin, "
            "position, created_at, updated_at) VALUES (:id, :key, :name, :descr, "
            ":perms, false, 10, now(), now())"
        ).bindparams(
            sa.bindparam('id', staff_id),
            sa.bindparam('key', STAFF_KEY),
            sa.bindparam('name', 'Staff'),
            sa.bindparam(
                'descr',
                'What the Baseline granted before RADD-825 narrowed it: read '
                'every project\'s issues and the wiki. Seeded to the accounts '
                'that predate the flip; grant or revoke it like any role.',
            ),
            sa.bindparam('perms', list(FLOOR_LEAVING), type_=sa.dialects.postgresql.JSONB),
        )
    )
    for user in users:
        conn.execute(
            sa.text(
                "INSERT INTO global_role_grants (id, role_id, user_id, created_at) "
                "VALUES (:id, :role_id, :user_id, now())"
            ).bindparams(
                sa.bindparam('id', uuid.uuid4()),
                sa.bindparam('role_id', staff_id),
                sa.bindparam('user_id', user.id),
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    staff = conn.execute(
        sa.text("SELECT id FROM roles WHERE key = :key").bindparams(
            sa.bindparam('key', STAFF_KEY)
        )
    ).first()
    if staff is not None:
        conn.execute(
            sa.text("DELETE FROM global_role_grants WHERE role_id = :id").bindparams(
                sa.bindparam('id', staff.id)
            )
        )
        conn.execute(
            sa.text("DELETE FROM roles WHERE id = :id").bindparams(
                sa.bindparam('id', staff.id)
            )
        )
    row = conn.execute(
        sa.text("SELECT id, permissions FROM roles WHERE key = 'baseline'")
    ).first()
    if row is None:
        return
    permissions = [p for p in row.permissions if p != 'item.read@own']
    permissions.extend(p for p in FLOOR_LEAVING if p not in permissions)
    conn.execute(
        sa.text("UPDATE roles SET permissions = :perms WHERE id = :id").bindparams(
            sa.bindparam('perms', permissions, type_=sa.dialects.postgresql.JSONB),
            sa.bindparam('id', row.id),
        )
    )
