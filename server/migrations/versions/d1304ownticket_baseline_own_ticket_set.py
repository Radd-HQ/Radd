"""RADD-1304: the Baseline gains the rest of the shared own-ticket set.

The Baseline is the one built-in role admins edit, so startup never rewrites it
(RADD-1305) and a change to its default ships here. This only ADDS the atoms it
lacked — attaching to your own ticket, sharing it, attaching where you are a
participant — and leaves whatever an admin has done to the row alone.

Revision ID: d1304ownticket
Revises: d1305staffviewer
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "d1304ownticket"
down_revision = "d1305staffviewer"
branch_labels = None
depends_on = None

ADDED = ("attachment.create@own", "participant.manage@own", "attachment.create@participant")


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT id, permissions FROM roles WHERE key = 'baseline'")).first()
    if row is None:
        return  # a fresh database: the startup seed writes the new default
    held = list(row.permissions or [])
    merged = held + [atom for atom in ADDED if atom not in held]
    if merged != held:
        conn.execute(
            sa.text("UPDATE roles SET permissions = CAST(:p AS jsonb) WHERE id = :id"),
            {"p": json.dumps(merged), "id": row.id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT id, permissions FROM roles WHERE key = 'baseline'")).first()
    if row is None:
        return
    kept = [atom for atom in (row.permissions or []) if atom not in ADDED]
    conn.execute(
        sa.text("UPDATE roles SET permissions = CAST(:p AS jsonb) WHERE id = :id"),
        {"p": json.dumps(kept), "id": row.id},
    )
