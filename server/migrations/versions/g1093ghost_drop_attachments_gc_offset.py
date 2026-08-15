"""Drop the attachments.gc ghost cursor (RADD-1093).

RADD-745 folded the standalone attachments GC into the unified events.cascade
consumer; the old consumer_offsets row survived and read as a permanently
"Stalled" worker (12 days, 21,813 backlog on the dev instance). This is the
one KNOWN ghost — future residue renders as "Retired" via the consumer_names
registry instead of being deleted blindly, because a disabled plugin's cursor
must survive its downtime.

Revision ID: g1093ghost
Revises: f677recovery
"""

import sqlalchemy as sa
from alembic import op

revision = "g1093ghost"
down_revision = "f677recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM consumer_offsets WHERE name = 'attachments.gc'"))


def downgrade() -> None:
    pass  # a deleted ghost has nothing to restore
