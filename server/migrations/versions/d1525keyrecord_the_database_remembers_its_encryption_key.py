"""d1525keyrecord: the database remembers which encryption key it was written with (RADD-1525)

One row holding the short id of the key file. `radd.backup.keyguard` records it
on the first boot and refuses to start on a later boot whose key file is
missing or different, instead of minting a replacement that decrypts nothing.

The table is created empty: the next start of an existing instance records the
key it has, which is the one its secrets were written with.

Revision ID: d1525keyrecord
Revises: d1524eventxact
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "d1525keyrecord"
down_revision = "d1524eventxact"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "encryption_key_record",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("key_id", sa.String(length=16), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("id = 1", name="ck_encryption_key_record_single_row"),
    )


def downgrade():
    op.drop_table("encryption_key_record")
