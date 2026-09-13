"""d1142princ: the Anyone and Signed-in users principal rows (spec 121, RADD-1142)

Two `users` rows with fixed ids and `source = 'principal'`. They are grant
SUBJECTS — a role granted to Anyone on a project is what makes the project
public, a role granted to Signed-in users is what lets any account contribute
there — and an unauthenticated request resolves to the Anyone row at the auth
seam, so a public project's reads run through the same resolvers as a
member's. Neither can log in, be assigned, be mailed, or be picked.

Idempotent: `auth.principals.ensure_principals` converges the same rows at
startup and in `radd.seed`; this migration exists so a running instance has
them the moment the code that resolves to them is deployed.

Revision ID: d1142princ
Revises: h1129ghconn
Create Date: 2026-09-13
"""

import sqlalchemy as sa
from alembic import op

revision = "d1142princ"
down_revision = "h1129ghconn"
branch_labels = None
depends_on = None

# Must match radd.modules.auth.principals.PRINCIPAL_ROWS.
PRINCIPALS = (
    ("00000000-0000-0000-0000-000000a4104e", "anyone@principals.invalid", "Anyone"),
    ("00000000-0000-0000-0000-0000005160ed", "signed-in@principals.invalid", "Signed-in users"),
)


def upgrade() -> None:
    conn = op.get_bind()
    for row_id, email, name in PRINCIPALS:
        conn.execute(
            sa.text(
                "INSERT INTO users (id, email, name, password_hash, instance_role, active, "
                "source, timezone, preferences, created_at, updated_at) "
                "VALUES (CAST(:id AS uuid), :email, :name, NULL, 'member', true, "
                "'principal', '', '{}'::jsonb, now(), now()) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, active = true, "
                "source = 'principal', instance_role = 'member'"
            ).bindparams(id=row_id, email=email, name=name)
        )


def downgrade() -> None:
    conn = op.get_bind()
    for row_id, _email, _name in PRINCIPALS:
        # Grants written against the rows go with them (FK CASCADE): a
        # downgrade makes every public project private again.
        conn.execute(
            sa.text("DELETE FROM users WHERE id = CAST(:id AS uuid)").bindparams(id=row_id)
        )
