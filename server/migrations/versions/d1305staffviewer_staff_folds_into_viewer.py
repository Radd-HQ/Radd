"""RADD-1305: the Staff role folds into Viewer.

Staff (seeded by d825flip so accounts that predate RADD-825 kept reading every
project and the wiki) holds exactly Viewer's atoms: item.read + page.read. Two
roles for one thing. Every Staff grant becomes the same grant of Viewer (same
subject, same scope; a duplicate that already exists is not doubled), and Staff
is deleted. No shim — the pre-V1 rule.

Builtin roles are seeded at STARTUP, not by migrations, so on a database where
Viewer does not exist yet the Staff row itself becomes Viewer; the startup sync
then gives it Viewer's exact definition.

Revision ID: d1305staffviewer
Revises: d1299slamet
"""
import sqlalchemy as sa
from alembic import op

revision = "d1305staffviewer"
down_revision = "d1299slamet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    staff = conn.execute(sa.text("SELECT id FROM roles WHERE key = 'staff'")).scalar()
    if staff is None:
        return
    viewer = conn.execute(sa.text("SELECT id FROM roles WHERE key = 'viewer'")).scalar()
    if viewer is None:
        conn.execute(
            sa.text(
                "UPDATE roles SET key = 'viewer', name = 'Viewer', is_builtin = true "
                "WHERE id = :staff"
            ),
            {"staff": staff},
        )
        return
    conn.execute(
        sa.text("""
            INSERT INTO global_role_grants
                (id, role_id, user_id, team_id, group_id, project_id, space_id,
                 expires_at, granted_by, created_at, updated_at)
            SELECT gen_random_uuid(), :viewer, g.user_id, g.team_id, g.group_id,
                   g.project_id, g.space_id, g.expires_at, g.granted_by, g.created_at, now()
            FROM global_role_grants g
            WHERE g.role_id = :staff
              AND NOT EXISTS (
                SELECT 1 FROM global_role_grants x
                WHERE x.role_id = :viewer
                  AND x.user_id IS NOT DISTINCT FROM g.user_id
                  AND x.team_id IS NOT DISTINCT FROM g.team_id
                  AND x.group_id IS NOT DISTINCT FROM g.group_id
                  AND x.project_id IS NOT DISTINCT FROM g.project_id
                  AND x.space_id IS NOT DISTINCT FROM g.space_id
              )
        """),
        {"viewer": viewer, "staff": staff},
    )
    conn.execute(sa.text("DELETE FROM global_role_grants WHERE role_id = :staff"), {"staff": staff})
    conn.execute(sa.text("DELETE FROM roles WHERE id = :staff"), {"staff": staff})


def downgrade() -> None:
    # Folding is lossy by design (the two roles were identical); nothing to restore.
    pass
