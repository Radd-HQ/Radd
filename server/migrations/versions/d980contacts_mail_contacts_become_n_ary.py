"""RADD-980: `mail_contacts` stops being one row per item.

The table was keyed on `item_id` alone, which encoded "one external contact per
ticket, ever". The reshape is in place — no shadow table, no backfill script,
because there is nothing to preserve beyond the rows themselves:

    id            new surrogate PK, generated for every existing row
    item_id       demoted from PK to an indexed FK
    is_primary    TRUE for every v1 row — each was, by construction, the only
                  one, and the singular seams (CSAT, the send_email `contact`
                  role, GET /items/{id}/mail-contact) must keep meaning it
    (item_id, email) UNIQUE — the constraint `upsert_contact` is idempotent on

`gen_random_uuid()` is a Postgres 13+ builtin, so the id fill needs no
extension. Under the no-backcompat rule the downgrade is exact rather than
lossless: collapsing back to one row per item DROPS every secondary contact,
which is precisely the information v1 could not hold.

Revision ID: d980contacts
Revises: d979mailbind
"""

import sqlalchemy as sa
from alembic import op

revision = "d980contacts"
down_revision = "d979mailbind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mail_contacts", sa.Column("id", sa.Uuid(), nullable=True))
    op.add_column(
        "mail_contacts",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Every surviving v1 row IS its item's requester: the old PK made a second
    # one unrepresentable.
    op.execute("UPDATE mail_contacts SET id = gen_random_uuid(), is_primary = true")
    op.alter_column("mail_contacts", "id", nullable=False)
    op.drop_constraint("pk_mail_contacts", "mail_contacts", type_="primary")
    op.create_primary_key("pk_mail_contacts", "mail_contacts", ["id"])
    op.create_index(
        op.f("ix_mail_contacts_item_id"), "mail_contacts", ["item_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_mail_contacts_item_id_email", "mail_contacts", ["item_id", "email"]
    )


def downgrade() -> None:
    # Lossy by definition — see the module docstring. The primary survives; the
    # contacts v1 had no way to store do not.
    op.execute(
        "DELETE FROM mail_contacts a USING mail_contacts b "
        "WHERE a.item_id = b.item_id AND b.is_primary AND NOT a.is_primary"
    )
    op.drop_constraint("uq_mail_contacts_item_id_email", "mail_contacts", type_="unique")
    op.drop_index(op.f("ix_mail_contacts_item_id"), table_name="mail_contacts")
    op.drop_constraint("pk_mail_contacts", "mail_contacts", type_="primary")
    op.create_primary_key("pk_mail_contacts", "mail_contacts", ["item_id"])
    op.drop_column("mail_contacts", "is_primary")
    op.drop_column("mail_contacts", "id")
