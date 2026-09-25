"""Reversible signature annotations and ordered domain rules."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1336signatures"
down_revision = "d1335widgets"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work_items", sa.Column("email_signature", sa.Text(), nullable=True))
    op.add_column("comments", sa.Column("email_signature", sa.Text(), nullable=True))
    op.create_table(
        "mail_signature_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
    )
    op.execute("INSERT INTO mail_signature_settings (id, rules) VALUES (1, '[]'::jsonb)")


def downgrade():
    op.drop_table("mail_signature_settings")
    op.drop_column("comments", "email_signature")
    op.drop_column("work_items", "email_signature")
