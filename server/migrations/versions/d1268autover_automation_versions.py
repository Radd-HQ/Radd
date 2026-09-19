"""RADD-1268: automation versions

`automations.version` (the current pointer) and `automation_versions`, one
immutable row per version. Existing automations get a v1 row copied from their
live content, so every history starts non-empty.

Revision ID: d1268autover
Revises: d1266autoruns
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d1268autover"
down_revision = "d1266autoruns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automations", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "automation_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("nodes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("edges", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("orientation", sa.String(length=16), nullable=False, server_default="vertical"),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("restored_from", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("automation_id", "version"),
    )
    op.create_index("ix_automation_versions_automation_id", "automation_versions", ["automation_id"])
    op.execute(
        """
        INSERT INTO automation_versions
            (id, automation_id, version, name, nodes, edges, orientation, created_by_id, created_at, note)
        SELECT gen_random_uuid(), id, 1, name, nodes, edges, orientation, created_by_id, updated_at,
               'Version history starts here (RADD-1268)'
        FROM automations
        """
    )


def downgrade() -> None:
    op.drop_table("automation_versions")
    op.drop_column("automations", "version")
