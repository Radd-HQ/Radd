"""d1499svcauto: the Automation account is a service account (RADD-1499)

The automations migration (d49968ce89b4) inserted the system actor without a
`source`, so it took the column default and was a LOCAL user — a person to
every picker and to the ledger's People filter. It is a service account: an
identity machines write as, key-only, no login, no mail. `auth.principals.
ensure_builtin_accounts` converges the same row at startup and in `radd.seed`;
this migration exists so a running instance is right the moment the code that
reads the source deploys.

Revision ID: d1499svcauto
Revises: d1492subtaskhome
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "d1499svcauto"
down_revision = "d1492subtaskhome"
branch_labels = None
depends_on = None

# Must match radd.modules.auth.types.SYSTEM_ACTOR_ID / _EMAIL / _NAME. A literal,
# not an import: a migration must keep meaning the same thing after the constant moves.
SYSTEM_ACTOR_ID = "00000000-0000-0000-0000-000000a70a70"
SYSTEM_ACTOR_EMAIL = "automation@radd.system"
SYSTEM_ACTOR_NAME = "Automation"


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO users (id, email, name, password_hash, instance_role, active, "
            "source, timezone, preferences, created_at, updated_at) "
            "VALUES (CAST(:id AS uuid), :email, :name, NULL, 'admin', true, "
            "'service', '', '{}'::jsonb, now(), now()) "
            "ON CONFLICT (id) DO UPDATE SET source = 'service', active = true, "
            "instance_role = 'admin'"
        ).bindparams(id=SYSTEM_ACTOR_ID, email=SYSTEM_ACTOR_EMAIL, name=SYSTEM_ACTOR_NAME)
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE users SET source = 'local' WHERE id = CAST(:id AS uuid)").bindparams(
            id=SYSTEM_ACTOR_ID
        )
    )
