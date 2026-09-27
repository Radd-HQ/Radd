"""The remaining replayed secrets: columns widen for at-rest ciphertext (RADD-1446).

`enc1:<b64(nonce || AES-GCM box)>` of an N-byte secret is 5 + 4·⌈(N+28)/3⌉
characters, so every VARCHAR that still held a replayed secret in plaintext is
too short for the sealed form of a value at its own limit: `storage_hosts.access_key`
(200), the code-host connections' `api_token` (500) and `webhook_secret` (200),
`alertmanager_receivers.token` (200) and `user_totp.secret` (64 — an 85-character
box for the 32-character base32 seed). The e1086secbox / d1424secrets precedent:
widen to TEXT here, and let the owners seal the values lazily (on the row's next
save, and by a startup sweep), because the secretbox key may not exist at
migration time. `ai_providers.api_key`, `storage_hosts.secret_key`,
`mail_sources.secret` and `mail_senders.secret` are TEXT already.

Revision ID: d1446secrets
Revises: d1457undeliverable
"""

import sqlalchemy as sa
from alembic import op

revision = "d1446secrets"
down_revision = "d1457undeliverable"
branch_labels = None
depends_on = None

#: (table, column, the VARCHAR length it was created with)
COLUMNS = (
    ("storage_hosts", "access_key", 200),
    ("forgejo_connections", "api_token", 500),
    ("forgejo_connections", "webhook_secret", 200),
    ("github_connections", "api_token", 500),
    ("github_connections", "webhook_secret", 200),
    ("gitlab_connections", "api_token", 500),
    ("gitlab_connections", "webhook_secret", 200),
    ("alertmanager_receivers", "token", 200),
    ("user_totp", "secret", 64),
)


def upgrade() -> None:
    for table, column, length in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Fails while a sealed value is over the old limit — clear or re-enter it first.
    for table, column, length in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Text(),
            type_=sa.String(length),
            existing_nullable=False,
        )
