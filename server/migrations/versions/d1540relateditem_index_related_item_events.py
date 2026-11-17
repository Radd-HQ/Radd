"""d1540relateditem: an index for "events about things attached to this item" (RADD-1540)

An item's History tab reads the events on the item itself (indexed) and the
events of whatever is attached to it — comments, worklogs, links, attachments —
found by `payload->'item'->>'id'`, which had no index: every such event on the
instance was read to find one item's. Measured on a 5.0M-event ledger: 1,531 ms
per History tab, 32 ms with this index.

Partial on purpose: item events are nine tenths of the ledger and are found by
`ix_events_entity`; indexing their `item.id` too would triple this index to
serve a branch that never asks for them.

Built CONCURRENTLY, so an instance keeps writing events while it builds (5 s on
the 5M-event ledger).

Revision ID: d1540relateditem
Revises: d1539descversion
Create Date: 2026-11-17
"""

from alembic import op

revision = "d1540relateditem"
down_revision = "d1539descversion"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_events_related_item "
            "ON events (((payload -> 'item') ->> 'id')) WHERE entity_type <> 'item'"
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_events_related_item")
