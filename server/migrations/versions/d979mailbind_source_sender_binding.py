"""RADD-979: bind a mail source to the sender that answers for it.

Two nullable columns, and they are two halves of one fact.

`mail_sources.sender_id` is the binding an admin sets ("Send replies from").
NULL keeps the behaviour every source had before: the single default sender.

`mail_messages.source_id` is the item's mail ORIGIN, recorded on INBOUND rows so
outbound can recall which address the conversation lives on. Without it the
binding would be unreachable at send time — an outbound message knows its item,
and nothing else connected an item back to the mailbox it arrived at.

Both are `ON DELETE SET NULL`. Deleting a relay must degrade a binding to the
default rather than delete the mailbox pointed at it, and deleting a mailbox
must not delete the thread history recorded against it.

Autogenerate's other diffs were reviewed and dropped as the known false
positives: the runtime-managed pgvector tables (`item_embeddings`,
`page_embeddings` — outside `Base.metadata` by design, spec 103), the example
plugin's `acme_notes`, four raw-SQL partial/expression indexes metadata cannot
see (`ix_backup_runs_started_at`, `ix_backup_schedules_due`,
`ix_comments_unresolved_inline`, `ix_events_automated`), the surviving
`doc_`→`page_` constraint names from RADD-701, and
`ix_mail_sources_default_project` — a hand-written index in `d958mailcfg` that
the model has never declared.

Revision ID: d979mailbind
Revises: d686emailtypes
"""

import sqlalchemy as sa
from alembic import op

revision = "d979mailbind"
down_revision = "d686emailtypes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mail_messages", sa.Column("source_id", sa.Uuid(), nullable=True))
    # Indexed for the delete path, not the read: the origin lookup rides the
    # existing (item_id, created_at) index, but SET NULL on a deleted source
    # would otherwise scan the whole message store.
    op.create_index(
        op.f("ix_mail_messages_source_id"), "mail_messages", ["source_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_mail_messages_source_id_mail_sources"),
        "mail_messages",
        "mail_sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("mail_sources", sa.Column("sender_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_mail_sources_sender_id_mail_senders"),
        "mail_sources",
        "mail_senders",
        ["sender_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_mail_sources_sender_id_mail_senders"), "mail_sources", type_="foreignkey"
    )
    op.drop_column("mail_sources", "sender_id")
    op.drop_constraint(
        op.f("fk_mail_messages_source_id_mail_sources"), "mail_messages", type_="foreignkey"
    )
    op.drop_index(op.f("ix_mail_messages_source_id"), table_name="mail_messages")
    op.drop_column("mail_messages", "source_id")
