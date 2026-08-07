"""RADD-952: mail_messages — the Message-ID store threading depends on.

Before this, nothing recorded the ids Radd SENT. `mail_contacts.last_message_id`
holds one INBOUND id per item and is overwritten on every reply, so a requester's
`In-Reply-To` named a value Radd had never seen and threading fell through to the
subject key — the last-resort mechanism, used as the only one.

The UNIQUE on `message_id` is load-bearing rather than hygiene: it IS the
idempotency mechanism. Two concurrent deliveries of the same message are what a
provider retry produces, and a SELECT-then-INSERT loses that race; the insert
races instead and the loser reads "duplicate".

Nothing is backfilled. The ids Radd sent before this migration were never
recorded anywhere, so there is nothing to recover — those threads fall back to
the subject key, which is exactly what they did already.

Revision ID: d952mailmsg
Revises: d943pagerefs
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d952mailmsg"
down_revision = "d943pagerefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", sa.String(998), nullable=False),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "comment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(998), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_mail_messages_message_id", "mail_messages", ["message_id"])
    op.create_index("ix_mail_messages_item_id", "mail_messages", ["item_id"])
    op.create_index("ix_mail_messages_created_at", "mail_messages", ["created_at"])
    op.create_index(
        "ix_mail_messages_item_created", "mail_messages", ["item_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("mail_messages")
