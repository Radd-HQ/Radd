"""d116graphs: automations become graphs (spec 116, RADD-914)

`automation_rules` becomes `automations`, and its three pipeline columns
(`event_conditions`, `condition_slq`, `actions`) become `nodes` + `edges`.

Every existing rule is a LINEAR graph, so the conversion is mechanical and
lossless:

    Trigger(trigger, schedule)
      -> Gate(event_conditions)     [matched on `true`]   -- omitted when NULL
      -> Filter(condition_slq)      [matched on `matched`] -- omitted when ''
      -> Action* (in list order)

The optional nodes are omitted rather than inserted empty, because a Gate with no
condition and a Filter with no query are not no-ops in the new model — they are
nodes that must be evaluated, and the migrated graph should execute exactly the
work the rule did, not the work plus two tautologies.

Actions chain: each action node feeds the next on its `out` port. That preserves
the old semantics (every action ran for every surviving item) while making the
sequence visible, and it is what lets someone open a migrated automation and
insert a filter between two actions without rebuilding it.

Downgrade is schema-only: the graph shape cannot be squeezed back into three
columns once anyone branches, and reconstructing a linear pipeline from a graph
that no longer is one would silently drop actions. Per the no-backcompat rule,
this is one-way.

Revision ID: d116graphs
Revises: d895compat
Create Date: 2026-08-06
"""
import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = 'd116graphs'
down_revision = 'd895compat'
branch_labels = None
depends_on = None


#: Literal rather than `AutomationTrigger.SCHEDULE`. A migration must keep doing
#: the same thing after the enum moves on, so it does not import live application
#: vocabulary — the value here is what the column held on 2026-08-06.
_SCHEDULE_TRIGGER = "schedule"


def _node(node_id: str, kind: str, type_: str, params: dict) -> dict:
    return {"id": node_id, "kind": kind, "type": type_, "params": params}


def _build_graph(row) -> tuple[list[dict], list[dict]]:
    """One rule -> (nodes, edges). Pure; unit-testable via the same shape the
    engine reads."""
    nodes: list[dict] = []
    edges: list[dict] = []

    scheduled = row.trigger == _SCHEDULE_TRIGGER
    trigger_params: dict = {"event": row.trigger}
    if scheduled and row.schedule is not None:
        trigger_params["schedule"] = row.schedule

    # `condition_slq` meant two different things depending on the trigger, and the
    # graph model separates them: a TRIGGER produces the initial item set, a FILTER
    # narrows one.
    #
    #   scheduled -> the SLQ SELECTED items from the whole corpus (there is no
    #                event and so no target item). It becomes the trigger's query.
    #   event     -> the SLQ FILTERED the event's single target item. It becomes
    #                a filter node.
    #
    # Migrating both to a filter node would leave every scheduled automation
    # filtering an empty set — running, matching nothing, and looking healthy.
    condition = (row.condition_slq or "").strip()
    if scheduled and condition:
        trigger_params["query"] = condition

    nodes.append(_node("trigger", "trigger", "trigger.event", trigger_params))
    previous, previous_port = "trigger", "out"

    if row.event_conditions:
        nodes.append(_node("gate", "gate", "gate.event", {"conditions": row.event_conditions}))
        edges.append({"source": previous, "port": previous_port, "target": "gate"})
        previous, previous_port = "gate", "true"

    if condition and not scheduled:
        nodes.append(_node("filter", "filter", "filter.slq", {"slq": condition}))
        edges.append({"source": previous, "port": previous_port, "target": "filter"})
        previous, previous_port = "filter", "matched"

    for index, action in enumerate(row.actions or []):
        node_id = f"action{index}"
        nodes.append(
            _node(
                node_id,
                "action",
                f"action.{action.get('type')}",
                action.get("params") or {},
            )
        )
        edges.append({"source": previous, "port": previous_port, "target": node_id})
        previous, previous_port = node_id, "out"

    return nodes, edges


def upgrade() -> None:
    conn = op.get_bind()

    op.rename_table('automation_rules', 'automations')
    op.add_column('automations', sa.Column('nodes', JSONB(), nullable=False, server_default='[]'))
    op.add_column('automations', sa.Column('edges', JSONB(), nullable=False, server_default='[]'))

    rows = conn.execute(
        sa.text(
            "SELECT id, trigger, event_conditions, condition_slq, actions, schedule "
            "FROM automations"
        )
    ).fetchall()
    for row in rows:
        nodes, edges = _build_graph(row)
        conn.execute(
            sa.text("UPDATE automations SET nodes = :nodes, edges = :edges WHERE id = :id"),
            {"nodes": json.dumps(nodes), "edges": json.dumps(edges), "id": row.id},
        )

    op.drop_column('automations', 'event_conditions')
    op.drop_column('automations', 'condition_slq')
    op.drop_column('automations', 'actions')

    # Renaming a table leaves every constraint NAME behind, still spelling the old
    # one. Postgres does not care, but `db.NAMING_CONVENTION` derives these names
    # from the table, so a later autogenerate would notice the drift and emit churn
    # (or collide). Both names are the convention's output for the new table, not
    # Postgres defaults — the real ones were read off the database, because
    # `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` is nothing like
    # the `<table>_<column>_fkey` a guess would produce.
    op.execute("ALTER TABLE automations RENAME CONSTRAINT pk_automation_rules TO pk_automations")
    op.execute(
        "ALTER TABLE automation_schedule_state "
        "RENAME CONSTRAINT fk_automation_schedule_state_rule_id_automation_rules "
        "TO fk_automation_schedule_state_rule_id_automations"
    )


def downgrade() -> None:
    # Schema only: a branching graph has no three-column form, and rebuilding one
    # would drop whichever actions did not sit on the main path.
    op.add_column('automations', sa.Column('event_conditions', JSONB(), nullable=True))
    op.add_column('automations', sa.Column('condition_slq', sa.Text(), nullable=False, server_default=''))
    op.add_column('automations', sa.Column('actions', JSONB(), nullable=False, server_default='[]'))
    op.drop_column('automations', 'nodes')
    op.drop_column('automations', 'edges')
    op.execute(
        "ALTER TABLE automation_schedule_state "
        "RENAME CONSTRAINT fk_automation_schedule_state_rule_id_automations "
        "TO fk_automation_schedule_state_rule_id_automation_rules"
    )
    op.execute("ALTER TABLE automations RENAME CONSTRAINT pk_automations TO pk_automation_rules")
    op.rename_table('automations', 'automation_rules')
