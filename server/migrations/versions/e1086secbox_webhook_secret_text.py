"""Webhook secrets: column widens for at-rest ciphertext (RADD-1086).

`enc1:<b64(nonce || AES-GCM box)>` of a 50-char signing secret is ~111 chars —
over the old VARCHAR(100). Values themselves are re-encrypted lazily by the
webhooks startup hook (the secretbox key may not exist at migration time on a
first boot), which is why this is a type change and not a data migration.

Revision ID: e1086secbox
Revises: d119join
"""

import sqlalchemy as sa
from alembic import op

revision = "e1086secbox"
down_revision = "d119join"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "webhook_endpoints",
        "secret",
        existing_type=sa.String(100),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "webhook_endpoints",
        "secret",
        existing_type=sa.Text(),
        type_=sa.String(100),
        existing_nullable=False,
    )
