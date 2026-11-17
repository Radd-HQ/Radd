"""d1572actorrecent: an index for "what this person did lately" (RADD-1572)

The "my tickets" list reads a person's newest item-scoped events to find the
issues they acted on. `ix_events_actor_id` finds a person's events but not the
recent ones: for an account with 189k events on a 5.0M-event ledger the read
visited every one of them (396 ms) to return the fortnight's.

`(actor_id, created_at)` answers it as a range. It replaces the single-column
index, whose every use it also serves (same leading column), so the ledger
carries the same number of indexes as before.

Built CONCURRENTLY, so an instance keeps writing events while it builds.

Revision ID: d1572actorrecent
Revises: d1560authepoch
Create Date: 2026-11-18
"""

from alembic import op

revision = "d1572actorrecent"
down_revision = "d1560authepoch"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_events_actor_created "
            "ON events (actor_id, created_at)"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_events_actor_id")


def downgrade():
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_events_actor_id ON events (actor_id)"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_events_actor_created")
