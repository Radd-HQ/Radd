"""Index existing key and numeric-prefix search semantics."""
from alembic import op

revision = "d1214scale"
down_revision = "d1213access"
branch_labels = None
depends_on = None


def upgrade():
    # Existing installations can have millions of rows. Concurrent builds
    # allow ordinary reads/writes while these secondary indexes are created.
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_search_key_prefix "
                   "ON search_index (lower(key) text_pattern_ops)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_search_number_prefix "
                   "ON search_index (split_part(key, '-', 2) text_pattern_ops)")


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_search_number_prefix")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_search_key_prefix")
