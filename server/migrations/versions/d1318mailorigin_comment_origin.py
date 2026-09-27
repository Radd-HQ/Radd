"""RADD-1318: comments record their origin; the mail receipt and resolution
notice settings are deleted.

`comments.origin` (inbound_mail | portal | automation | import, NULL = a
person) replaces "the author is the SYSTEM user" as the test the outbound relay
and the SLA use. Backfill: a SYSTEM-authored comment the mail store links to an
INBOUND message is `inbound_mail` (a recognised sender's mail is their own
comment and stays NULL); any other SYSTEM-authored comment was an
automation's. The `mail_ack_body` / `mail_send_resolved` rows are LEFT IN PLACE:
this migration used to delete them when both behaviours became automation
templates, but RADD-1368 brought the settings back under the same keys (default
OFF) and a deleted override is a destroyed receipt text (RADD-1453).

Revision ID: d1318mailorigin
Revises: d1317alertrecv
"""

import sqlalchemy as sa
from alembic import op

revision = "d1318mailorigin"
down_revision = "d1317alertrecv"
branch_labels = None
depends_on = None

SYSTEM_ACTOR_ID = "00000000-0000-0000-0000-000000a70a70"


def upgrade() -> None:
    op.add_column("comments", sa.Column("origin", sa.String(length=20), nullable=True))
    op.execute(
        f"""
        UPDATE comments SET origin = 'inbound_mail'
        WHERE id IN (
            SELECT comment_id FROM mail_messages
            WHERE direction = 'inbound' AND comment_id IS NOT NULL
        ) AND author_id = '{SYSTEM_ACTOR_ID}'
        """
    )
    op.execute(
        f"""
        UPDATE comments SET origin = 'automation'
        WHERE origin IS NULL AND author_id = '{SYSTEM_ACTOR_ID}'
        """
    )


def downgrade() -> None:
    op.drop_column("comments", "origin")
