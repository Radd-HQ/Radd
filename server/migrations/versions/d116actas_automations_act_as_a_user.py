"""d116actas: automations act as a person, and causation leaves the actor (spec 116)

Two columns, one idea.

`automations.created_by_id` — an automation now has an AUTHOR, and its actions
run as that person by default. A node may name someone else, which requires the
new `automation.act_as` atom. Nullable: rows written before this have no author
to name, and they keep running as the system actor, exactly as they always did.

`events.automated` — THE LOOP GUARD, moved. It used to be enough that engine
mutations carried SYSTEM_ACTOR_ID, because `should_process` skipped events whose
actor was the system user. "Act as" ends that: an action can run as a real
person, whose events are indistinguishable from their own, so an automation
whose action re-matches its own trigger would spin forever. Causation is now
recorded on the EVENT and identity is left to mean identity.

Existing rows are backfilled `automated = (actor_id = SYSTEM_ACTOR_ID)`, which is
precisely what the old predicate inferred — so the guard behaves identically on
history. The predicate keeps the actor check as a second arm anyway, for the
scheduler's synthetic events and for anything emitted between deploy and
backfill.

Revision ID: d116actas
Revises: d116multi
Create Date: 2026-08-06
"""
import sqlalchemy as sa
from alembic import op

revision = 'd116actas'
down_revision = 'd116multi'
branch_labels = None
depends_on = None

#: The engine's system actor. A literal, not an import: a migration must keep
#: meaning the same thing after the constant moves.
_SYSTEM_ACTOR_ID = '00000000-0000-0000-0000-000000a70a70'


def upgrade() -> None:
    op.add_column(
        'automations',
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        'fk_automations_created_by_id_users',
        'automations', 'users', ['created_by_id'], ['id'], ondelete='SET NULL',
    )

    op.add_column(
        'events',
        sa.Column('automated', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Backfill to exactly what the old actor-based predicate inferred, so the
    # loop guard's answer on history does not change under it.
    op.execute(
        f"UPDATE events SET automated = TRUE WHERE actor_id = '{_SYSTEM_ACTOR_ID}'"
    )
    # Partial index: consumers ask "is this one automated" per row, but the
    # engine's hot path filters them OUT, and indexing only the true rows keeps
    # it small on a table that grows forever.
    op.create_index(
        'ix_events_automated', 'events', ['id'], postgresql_where=sa.text('automated')
    )


def downgrade() -> None:
    op.drop_index('ix_events_automated', table_name='events')
    op.drop_column('events', 'automated')
    op.drop_constraint('fk_automations_created_by_id_users', 'automations', type_='foreignkey')
    op.drop_column('automations', 'created_by_id')
