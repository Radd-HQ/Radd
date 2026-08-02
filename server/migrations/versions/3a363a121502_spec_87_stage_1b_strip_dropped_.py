"""spec 87 stage 1b strip dropped permission atoms

Revision ID: 3a363a121502
Revises: 466eca47eeee

"""
from alembic import op
import sqlalchemy as sa


revision = '3a363a121502'
down_revision = '466eca47eeee'
branch_labels = None
depends_on = None


# Atoms spec 87 removed from the Permission enum because nothing could ever
# check them: no endpoint existed (user.delete, import.run) or the resource
# decides by spec-57 ownership instead (dashboard.update/delete).
DROPPED = ("user.delete", "import.run", "dashboard.update", "dashboard.delete")


def upgrade() -> None:
    """Strip the dropped atoms out of stored role permission sets.

    `RoleRead.permissions` is `list[Permission]`, so a stale string left in the
    JSONB would fail validation and 500 `GET /roles` — and `combine_permissions`
    would raise on it mid-authorization. The spec-86 workspace.manage rewrite is
    the precedent for editing role JSONB in a migration.
    """
    op.execute(
        sa.text(
            """
            UPDATE roles
               SET permissions = COALESCE(
                     (SELECT jsonb_agg(to_jsonb(atom))
                        FROM jsonb_array_elements_text(permissions) AS atom
                       WHERE atom <> ALL(:dropped)),
                     '[]'::jsonb)
             WHERE permissions ?| :dropped
            """
        ).bindparams(sa.bindparam("dropped", value=list(DROPPED), type_=sa.ARRAY(sa.Text)))
    )


def downgrade() -> None:
    # Irreversible by design: which roles held the dropped atoms is not recorded,
    # and nothing consumed them, so there is nothing to restore.
    pass
