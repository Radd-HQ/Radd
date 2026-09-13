"""d1147pubkb: a public wiki space is the Public role granted to Anyone (spec 121 §5, RADD-1147)

Spec 74's `page_spaces.public` was a second authorisation model — a boolean
consulted by a parallel router. Every space flagged public becomes one
space-scoped `global_role_grants` row (the seeded Public role → the Anyone
principal), which the ordinary page reads honour through the RADD-791
space-scoped resolvers; then the column is dropped.

The Public role may not exist yet on an instance upgrading straight to this
release (builtin roles are ensured at STARTUP, after migrations run), so the
migration seeds it when missing — the same permission set `auth.types`
declares — and adds `page.read` to a row an earlier dev build created
without it.

Revision ID: d1147pubkb
Revises: d1143vis
Create Date: 2026-09-13
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d1147pubkb"
down_revision = "d1143vis"
branch_labels = None
depends_on = None

# Must match radd.modules.auth.principals.ANYONE_ID / auth.types BUILTIN_ROLES.
ANYONE_ID = "00000000-0000-0000-0000-000000a4104e"
PUBLIC_ROLE_KEY = "public"
PUBLIC_ROLE_PERMISSIONS = [
    "item.read@public",
    "page.read",
    "label.read",
    "cycle.read",
    "team.read",
]


def _public_role_id(conn) -> uuid.UUID:
    row = conn.execute(
        sa.text("SELECT id, permissions FROM roles WHERE key = :key").bindparams(key=PUBLIC_ROLE_KEY)
    ).first()
    if row is None:
        role_id = uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO roles (id, key, name, description, permissions, is_builtin, "
                "position, created_at, updated_at) VALUES (:id, :key, :name, :descr, :perms, "
                "true, 4, now(), now())"
            ).bindparams(
                sa.bindparam("id", role_id),
                sa.bindparam("key", PUBLIC_ROLE_KEY),
                sa.bindparam("name", "Public"),
                sa.bindparam(
                    "descr",
                    "What the world holds where granted: a public project's public "
                    "issues, a public space's pages. Granted to Anyone by the Public switch.",
                ),
                sa.bindparam("perms", PUBLIC_ROLE_PERMISSIONS, type_=JSONB),
            )
        )
        return role_id
    if "page.read" not in list(row.permissions):
        conn.execute(
            sa.text("UPDATE roles SET permissions = :perms WHERE id = :id").bindparams(
                sa.bindparam("perms", list(row.permissions) + ["page.read"], type_=JSONB),
                sa.bindparam("id", row.id),
            )
        )
    return row.id


def upgrade() -> None:
    conn = op.get_bind()
    public_spaces = conn.execute(
        sa.text("SELECT id FROM page_spaces WHERE public = true")
    ).fetchall()
    if public_spaces:
        role_id = _public_role_id(conn)
        for space in public_spaces:
            conn.execute(
                sa.text(
                    "INSERT INTO global_role_grants (id, role_id, user_id, space_id, created_at) "
                    "VALUES (:id, :role_id, CAST(:user_id AS uuid), :space_id, now()) "
                    "ON CONFLICT DO NOTHING"
                ).bindparams(
                    sa.bindparam("id", uuid.uuid4()),
                    sa.bindparam("role_id", role_id),
                    sa.bindparam("user_id", ANYONE_ID),
                    sa.bindparam("space_id", space.id),
                )
            )
    else:
        # Still converge the role's permission set on a dev build that seeded
        # it before page.read joined.
        if conn.execute(sa.text("SELECT 1 FROM roles WHERE key = 'public'")).first():
            _public_role_id(conn)
    op.drop_column("page_spaces", "public")


def downgrade() -> None:
    op.add_column(
        "page_spaces",
        sa.Column("public", sa.Boolean(), server_default="false", nullable=False),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE page_spaces SET public = true WHERE id IN ("
            "SELECT g.space_id FROM global_role_grants g JOIN roles r ON r.id = g.role_id "
            "WHERE r.key = :key AND g.user_id = CAST(:anyone AS uuid) AND g.space_id IS NOT NULL)"
        ).bindparams(key=PUBLIC_ROLE_KEY, anyone=ANYONE_ID)
    )
