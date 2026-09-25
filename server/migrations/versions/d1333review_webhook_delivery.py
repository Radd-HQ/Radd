"""Track webhook delivery claims and the source ordering of CI reports."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1333review"
down_revision = "d1332review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vcs_deliveries",
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("digest", sa.String(64), primary_key=True))
    op.add_column("item_vcs_links", sa.Column("ci_run_id", sa.BigInteger(), nullable=True))
    op.add_column("item_vcs_links", sa.Column("ci_source_updated_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("item_vcs_links", "ci_source_updated_at")
    op.drop_column("item_vcs_links", "ci_run_id")
    op.drop_table("vcs_deliveries")
