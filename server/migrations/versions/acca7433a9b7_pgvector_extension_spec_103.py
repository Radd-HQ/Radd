"""pgvector extension spec 103

Guarded: creates the `vector` extension when the server offers it, and is a
clean no-op otherwise — semantic search degrades to FTS-only on a plain
Postgres. The embeddings tables/indexes are deliberately NOT here: they are
runtime-managed by `radd.modules.ai.embeddings.ensure_schema()` (idempotent
startup hook), which also covers a deploy that swaps to a pgvector-enabled
image AFTER this migration already ran, and keeps halfvec types out of
Alembic autogenerate entirely.

Revision ID: acca7433a9b7
Revises: 164d25776678

"""
import logging

from alembic import op
import sqlalchemy as sa

revision = 'acca7433a9b7'
down_revision = '164d25776678'
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()
    available = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    ).scalar()
    if available:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    else:
        logger.warning(
            "pgvector is not available on this server — semantic search stays off "
            "(FTS-only). Install the extension (pgvector/pgvector image) and restart; "
            "the schema is created at startup, no re-migration needed."
        )


def downgrade() -> None:
    # Leave the extension in place: other databases on the server may use it.
    pass
