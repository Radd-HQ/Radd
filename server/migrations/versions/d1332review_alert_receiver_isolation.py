"""Isolate receiver deduplication and remember completed environment setup."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "d1332review"
down_revision = "d1321mirror"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alert_items", sa.Column("id", postgresql.UUID(as_uuid=True),
                                         nullable=False, server_default=sa.text("gen_random_uuid()")))
    op.drop_constraint(sa.inspect(op.get_bind()).get_pk_constraint("alert_items")["name"], "alert_items", type_="primary")
    op.create_primary_key("pk_alert_items", "alert_items", ["id"])
    op.create_unique_constraint("uq_alert_items_receiver_fingerprint", "alert_items", ["receiver_id", "fingerprint"])
    op.create_table("alertmanager_seed", sa.Column("key", sa.String(40), primary_key=True))
    op.execute("INSERT INTO alertmanager_seed (key) SELECT 'environment' WHERE EXISTS (SELECT 1 FROM alertmanager_receivers)")


def downgrade():
    # Different receivers may now legitimately have the same fingerprint.
    # Refuse the old constraint if duplicates exist rather than deleting data.
    op.drop_table("alertmanager_seed")
    op.drop_constraint("uq_alert_items_receiver_fingerprint", "alert_items", type_="unique")
    op.drop_constraint("pk_alert_items", "alert_items", type_="primary")
    op.create_primary_key("pk_alert_items", "alert_items", ["fingerprint"])
    op.drop_column("alert_items", "id")
