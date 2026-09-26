"""RADD-1370: an Alertmanager receiver's own settings — comment on repeats and
resolution, a label for the issues it creates, and the state a resolved alert's
issue moves to. Off/empty for every row, existing ones included: RADD-1317
removed the unconditional behaviour, and nothing starts again unasked.

Revision ID: d1370alertpolicy
Revises: d1369vcspolicy
"""

import sqlalchemy as sa
from alembic import op

revision = "d1370alertpolicy"
down_revision = "d1369vcspolicy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alertmanager_receivers", sa.Column("comment_updates", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("alertmanager_receivers", sa.Column("label", sa.String(100), nullable=False, server_default=""))
    op.add_column("alertmanager_receivers", sa.Column("resolve_state_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_alertmanager_receivers_resolve_state", "alertmanager_receivers", "states",
        ["resolve_state_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_alertmanager_receivers_resolve_state", "alertmanager_receivers", type_="foreignkey")
    op.drop_column("alertmanager_receivers", "resolve_state_id")
    op.drop_column("alertmanager_receivers", "label")
    op.drop_column("alertmanager_receivers", "comment_updates")
