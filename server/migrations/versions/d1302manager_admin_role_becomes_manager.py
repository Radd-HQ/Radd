"""RADD-1302: the built-in "Admin" role becomes "Manager".

Renamed so the project/space role no longer reads as the instance
"Administrator" flag it sits beside. The KEY changes too (admin -> manager) —
no alias, the pre-V1 rule; grants reference the role by id, so they follow.
The startup sync (RADD-1305) then writes the new name, description and ladder
permissions onto the row.

Revision ID: d1302manager
Revises: d1304ownticket
"""
import sqlalchemy as sa
from alembic import op

revision = "d1302manager"
down_revision = "d1304ownticket"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "UPDATE roles SET key = 'manager', name = 'Manager' WHERE key = 'admin' AND is_builtin"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "UPDATE roles SET key = 'admin', name = 'Admin' WHERE key = 'manager' AND is_builtin"
    ))
