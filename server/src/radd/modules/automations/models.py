import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Automation(Base, TimestampMixin):
    """A graph of nodes and edges (spec 116) executed when its TRIGGER node fires.

    Was `AutomationRule` with three columns — `event_conditions`, `condition_slq`
    and `actions` — which could only express a linear pipeline where every action
    ran against every surviving item. "Rule" stopped being accurate the moment the
    thing could branch.

    Deliberately not called a workflow: `radd.modules.workflow` owns item states
    and transitions, the nouns a board's columns are made of.

    `nodes` and `edges` are raw JSON validated on write by `graph.validate` (and
    re-checked on read, so a hand-crafted row cannot wedge the engine). The typed
    view is `graph.Node` / `graph.Edge`.
    """

    __tablename__ = "automations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # [{id, kind, type, params, x, y}] — see graph.Node.
    nodes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{source, port, target}] — see graph.Edge.
    edges: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Which way the canvas flows. A property of the graph rather than of the
    # viewer: a graph someone arranged deliberately opens that way for everyone.
    orientation: Mapped[str] = mapped_column(String(16), default="vertical")
    # Who wrote it. Every action runs as this person unless the action names
    # someone else, which needs `automation.act_as`. Nullable because rows
    # predating spec 116 have no author to name — those keep running as the
    # system actor, which is what they always did.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TriggerBinding(Base):
    """One TRIGGER node of a graph, projected into a row the engine can query.

    Spec 116 revision: an automation may hold SEVERAL triggers — "when an item is
    created, OR every Monday" is one set of actions, not two graphs kept in step
    by hand. That makes the old denormalised `automations.trigger` /
    `automations.schedule` columns unable to hold the answer, so they become
    these rows: one per trigger node, rebuilt from the graph on every write.

    The graph stays the source of truth; this is its index. It exists because the
    engine must answer "which automations care about item.created" without
    parsing every stored graph on every event, and the scheduler must find due
    triggers without loading them all.

    Named TriggerBinding, not AutomationTrigger, because `types.AutomationTrigger`
    is already the MANUAL/SCHEDULE sentinel enum and two things with one name in
    one module is how the wrong one gets imported.
    """

    __tablename__ = "automation_triggers"

    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), primary_key=True
    )
    #: The graph node this row projects. Part of the key: two schedule triggers in
    #: one graph each need their own next_run_at, which a per-automation key
    #: cannot express.
    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: An event type from the catalog, or the "manual"/"schedule" sentinel.
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    #: {kind, minutes|time|days|expression} on a schedule trigger; NULL otherwise.
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class AutomationScheduleState(Base):
    """Scheduler bookkeeping per scheduled TRIGGER (spec 69, re-keyed by spec 116)
    — mirrors the sla_item_states pattern: engine state kept apart from user data.

    Keyed by (automation_id, node_id) rather than by automation: a graph with two
    schedule triggers has two independent clocks, and a per-automation key would
    let one overwrite the other's next_run_at.

    The row is (re)computed on create/update/enable and advanced by the scheduler
    in the same transaction that emits `automation.scheduled` (at-most-once per
    occurrence; a missed window fires once on the next tick, never a backlog)."""

    __tablename__ = "automation_schedule_state"

    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_run_at: Mapped[datetime]  # naive UTC, like every engine timestamp
    last_run_at: Mapped[datetime | None]
