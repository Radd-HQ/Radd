"""d844partrel: the second-reporter floor — @participant joins the Baseline and Requester rows (RADD-844)

Decision (2026-08-05): a participant is a second reporter. The Baseline gains
`item.read@participant` + `comment.write@participant` (open the shared item,
discuss it) and `comment.write@own` (the FIRST reporter gets the same
discussion right — a staff reporter in a foreign project could read their own
ticket but never reply to it). The Requester floor gains
`item.read@participant` so an email-provisioned requester shared into a
colleague's ticket can follow it; its `comment.write` is already unqualified.

Append-if-absent on the LIVE rows — the Baseline is deliberately editable, so
anything an admin added stays untouched. A fresh database skips this entirely:
the seed writes the new shape.

Revision ID: d844partrel
Revises: d855vieworder
Create Date: 2026-08-05
"""
import sqlalchemy as sa
from alembic import op

revision = 'd844partrel'
down_revision = 'd855vieworder'
branch_labels = None
depends_on = None

GAINS = {
    'baseline': ('item.read@participant', 'comment.write@own', 'comment.write@participant'),
    'requester': ('item.read@participant',),
}


def _update(conn, key: str, permissions: list[str]) -> None:
    conn.execute(
        sa.text("UPDATE roles SET permissions = :perms WHERE key = :key").bindparams(
            sa.bindparam('perms', permissions, type_=sa.dialects.postgresql.JSONB),
            sa.bindparam('key', key),
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    for key, gains in GAINS.items():
        row = conn.execute(
            sa.text("SELECT permissions FROM roles WHERE key = :key").bindparams(
                sa.bindparam('key', key)
            )
        ).first()
        if row is None:
            continue  # fresh database: the seed writes the new shape
        permissions = list(row.permissions)
        permissions.extend(p for p in gains if p not in permissions)
        _update(conn, key, permissions)


def downgrade() -> None:
    conn = op.get_bind()
    for key, gains in GAINS.items():
        row = conn.execute(
            sa.text("SELECT permissions FROM roles WHERE key = :key").bindparams(
                sa.bindparam('key', key)
            )
        ).first()
        if row is None:
            continue
        _update(conn, key, [p for p in row.permissions if p not in gains])
