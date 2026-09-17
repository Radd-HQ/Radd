"""Storage hosts must opt in before images can leave through service-desk mail."""
from alembic import op
import sqlalchemy as sa

revision = "d988emailimages"
down_revision = "d1195commentauthor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("storage_hosts", sa.Column(
        "email_images_allowed", sa.Boolean(), nullable=False, server_default=sa.false()
    ))


def downgrade() -> None:
    op.drop_column("storage_hosts", "email_images_allowed")
