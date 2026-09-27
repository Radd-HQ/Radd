"""Importer credentials: the column widens for at-rest ciphertext (RADD-1424).

`enc1:<b64(nonce || AES-GCM box)>` of an N-byte credential is 5 + 4·⌈(N+28)/3⌉
characters, so VARCHAR(500) holds a credential of at most 341 bytes — while the
Jira schema accepts 500 characters and Confluence's sets no limit. The e1086secbox
precedent: widen to TEXT here, and let the owners seal the values lazily (on the
row's next save, and at boot), because the secretbox key may not exist at
migration time. `sso_providers.client_secret` is TEXT already, and the LDAP bind
password lives in `scoped_settings.value` (JSONB), so neither needs a change.

Revision ID: d1424secrets
Revises: d1396slaqueue
"""

import sqlalchemy as sa
from alembic import op

revision = "d1424secrets"
down_revision = "d1396slaqueue"
branch_labels = None
depends_on = None

TABLES = ("jira_connections", "confluence_connections")


def upgrade() -> None:
    for table in TABLES:
        op.alter_column(
            table,
            "credential",
            existing_type=sa.String(500),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Fails while a sealed credential is over 500 characters — clear it first.
    for table in TABLES:
        op.alter_column(
            table,
            "credential",
            existing_type=sa.Text(),
            type_=sa.String(500),
            existing_nullable=False,
        )
