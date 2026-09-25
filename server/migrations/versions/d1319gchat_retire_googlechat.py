"""RADD-1319: the Google Chat env fan-out is retired.

The `googlechat` plugin posted `RADD_GOOGLECHAT_EVENT_TYPES` to one env webhook
with no switch in the product. Posting to chat is the Post to chat automation
action now (template "Post new issues and SLA breaches to chat"). This drops
the retired consumer's stream cursor and any plugin-manager row it left.

Revision ID: d1319gchat
Revises: d1318mailorigin
"""

from alembic import op

revision = "d1319gchat"
down_revision = "d1318mailorigin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM consumer_offsets WHERE name = 'googlechat.notifier'")
    op.execute("DELETE FROM installed_plugins WHERE id = 'googlechat'")


def downgrade() -> None:
    pass  # the rows were a retired consumer's; nothing reads them
