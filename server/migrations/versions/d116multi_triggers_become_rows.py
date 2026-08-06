"""d116multi: triggers become rows, so a graph can have several (spec 116)

The first cut of spec 116 kept `automations.trigger` and `automations.schedule`
as denormalised copies of THE trigger node, because a graph had exactly one. It
can now have several — "when an item is created, OR every Monday" is one set of
actions, not two graphs kept in step by hand — and a single column cannot hold
that answer.

So each TRIGGER node projects into an `automation_triggers` row, rebuilt from the
graph on every write. The graph stays the source of truth; these rows are the
index the engine queries ("which automations care about item.created") and the
scheduler walks.

`automation_schedule_state` is re-keyed from (rule_id) to (automation_id,
node_id) for the same reason: two schedule triggers in one graph keep two
independent clocks, and the old key would let one overwrite the other's
next_run_at.

Existing rows convert exactly: every automation has exactly one trigger node
today, so each produces exactly one binding, carrying the columns' values and the
node id read out of the stored graph.

Revision ID: d116multi
Revises: d116graphs
Create Date: 2026-08-06
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = 'd116multi'
down_revision = 'd116graphs'
branch_labels = None
depends_on = None

#: The node kind whose rows we project. A literal, not an import: a migration
#: must keep meaning the same thing after the enum moves on.
_TRIGGER_KIND = "trigger"
_DEFAULT_TRIGGER_NODE_ID = "trigger"


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        'automation_triggers',
        sa.Column('automation_id', sa.Uuid(), nullable=False),
        sa.Column('node_id', sa.String(length=64), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('schedule', JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ['automation_id'], ['automations.id'], ondelete='CASCADE',
            name='fk_automation_triggers_automation_id_automations',
        ),
        sa.PrimaryKeyConstraint('automation_id', 'node_id', name='pk_automation_triggers'),
    )
    op.create_index('ix_automation_triggers_event_type', 'automation_triggers', ['event_type'])

    # Project the existing single trigger. The node id comes from the graph
    # rather than being assumed: d116graphs names it "trigger", but a graph
    # edited since may not, and guessing would orphan the binding.
    rows = conn.execute(sa.text("SELECT id, trigger, schedule, nodes FROM automations")).fetchall()
    for row in rows:
        node_id = _DEFAULT_TRIGGER_NODE_ID
        for node in row.nodes or []:
            if isinstance(node, dict) and node.get("kind") == _TRIGGER_KIND:
                node_id = str(node.get("id") or _DEFAULT_TRIGGER_NODE_ID)
                break
        conn.execute(
            sa.text(
                "INSERT INTO automation_triggers (automation_id, node_id, event_type, schedule) "
                "VALUES (:aid, :nid, :evt, CAST(:sched AS JSONB))"
            ),
            {
                "aid": row.id,
                "nid": node_id,
                "evt": row.trigger,
                "sched": json.dumps(row.schedule) if row.schedule is not None else None,
            },
        )

    op.drop_column('automations', 'trigger')
    op.drop_column('automations', 'schedule')
    op.add_column(
        'automations',
        sa.Column('orientation', sa.String(length=16), nullable=False, server_default='vertical'),
    )

    # Re-key the scheduler state. The node id is the same one just projected, so
    # the join is on the binding rather than on a second guess.
    op.add_column(
        'automation_schedule_state',
        sa.Column('node_id', sa.String(length=64), nullable=False, server_default=_DEFAULT_TRIGGER_NODE_ID),
    )
    conn.execute(
        sa.text(
            "UPDATE automation_schedule_state s SET node_id = t.node_id "
            "FROM automation_triggers t WHERE t.automation_id = s.rule_id"
        )
    )
    op.alter_column('automation_schedule_state', 'rule_id', new_column_name='automation_id')
    # Renaming the column leaves the FK spelling the old one. `NAMING_CONVENTION`
    # derives the name from the column, so a later autogenerate would notice the
    # drift — the same stale-name trap the pk/fk rename in d116graphs hit.
    op.execute(
        "ALTER TABLE automation_schedule_state "
        "RENAME CONSTRAINT fk_automation_schedule_state_rule_id_automations "
        "TO fk_automation_schedule_state_automation_id_automations"
    )
    op.drop_constraint('pk_automation_schedule_state', 'automation_schedule_state', type_='primary')
    op.create_primary_key(
        'pk_automation_schedule_state', 'automation_schedule_state', ['automation_id', 'node_id']
    )
    op.alter_column('automation_schedule_state', 'node_id', server_default=None)


def downgrade() -> None:
    # One-way: several triggers cannot be squeezed back into one column, and
    # picking one would silently drop the rest.
    op.add_column('automations', sa.Column('trigger', sa.String(length=100), nullable=False,
                                           server_default='manual'))
    op.add_column('automations', sa.Column('schedule', JSONB(), nullable=True))
    op.drop_column('automations', 'orientation')
    op.drop_constraint('pk_automation_schedule_state', 'automation_schedule_state', type_='primary')
    op.execute(
        "ALTER TABLE automation_schedule_state "
        "RENAME CONSTRAINT fk_automation_schedule_state_automation_id_automations "
        "TO fk_automation_schedule_state_rule_id_automations"
    )
    op.alter_column('automation_schedule_state', 'automation_id', new_column_name='rule_id')
    op.drop_column('automation_schedule_state', 'node_id')
    op.create_primary_key('pk_automation_schedule_state', 'automation_schedule_state', ['rule_id'])
    op.drop_index('ix_automation_triggers_event_type', table_name='automation_triggers')
    op.drop_table('automation_triggers')
