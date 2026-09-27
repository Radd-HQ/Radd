"""Notifications carry the email channel's verdict (RADD-1457).

`emailed_at` used to be stamped for every row the channel was finished with —
sent, but also undeliverable (no mail transport), unmailable and given up — so
the record said "emailed" about rows nobody was ever sent. `delivery` holds the
verdict (`notify.types.NotificationDelivery`: pending, sent, undeliverable,
dropped) and `emailed_at` is set by a send alone from here on. Existing rows
cannot be told apart, so every stamped row backfills as `sent` and the rest as
`pending`: the mail loops select on `delivery`, and a pending unread recent row
is exactly what they would have selected on `emailed_at IS NULL` before.

Revision ID: d1457undeliverable
Revises: d1424secrets
"""

import sqlalchemy as sa
from alembic import op

revision = "d1457undeliverable"
down_revision = "d1424secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("delivery", sa.String(length=20), nullable=False, server_default="pending"),
    )
    op.execute("UPDATE notifications SET delivery = 'sent' WHERE emailed_at IS NOT NULL")


def downgrade() -> None:
    # Rows the channel dropped or recorded undeliverable become selectable again
    # (`emailed_at IS NULL`) — the pre-RADD-1457 reading of the same rows.
    op.drop_column("notifications", "delivery")
