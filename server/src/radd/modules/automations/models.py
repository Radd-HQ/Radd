import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text
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


class ValidationBinding(Base):
    """What one VALIDATE trigger node governs, projected into queryable rows
    (spec 119) — the same shape `TriggerBinding` is, for the same reason.

    Intake has to answer "does anything validate a draft in project P, of type T,
    submitted through form F" on the request path, before the person's Submit
    click has returned. Parsing every stored graph to find out is the version
    that gets slower with every automation anyone writes, so the graph stays the
    source of truth and this is its index, rebuilt wholesale on every write by
    `service._sync_validations`.

    One row per (trigger node, target). A graph may govern the incident form AND
    the Bug type in two projects — that is a LIST of scoped targets, so it is a
    list of rows; three nullable columns would have made "which of these did the
    author actually mean" a question the reader has to answer.

    `target_id` carries no foreign key, and cannot: the target is polymorphic
    across three owners' tables. A deleted form simply stops matching anything,
    which is the same degradation a card layout's departed field gets — the
    binding is stale, not corrupt.
    """

    __tablename__ = "automation_validations"

    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: A `ValidationTargetKind` value — form | issue_type | project.
    target_kind: Mapped[str] = mapped_column(String(16), primary_key=True, index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, index=True)
    #: A `ValidationMode` value. Per BINDING rather than per automation: the same
    #: checks may be advice on one project's intake and law on another's.
    mode: Mapped[str] = mapped_column(String(16))


class TeamAssignmentCursor(Base):
    """Round-robin position for the `assign_round_robin` action (RADD-1044).

    ONE row per TEAM, not per rule or per automation: the point of round-robin is
    fair distribution across the team, so two rules that both assign from the same
    team must share the rotation — a per-rule cursor would let each restart it and
    pile work on the first member. Engine state kept apart from user data, the same
    shape AutomationScheduleState and sla_item_states use.

    `last_assigned_user_id` is the member the last SUCCESSFUL assignment landed on
    (advanced inside the same SAVEPOINT as the assignment, so a rolled-back apply
    does not move the rotation). The next pick is the first eligible member ordered
    after it by user id, wrapping — see `round_robin.pick_next`.

    Nullable + SET NULL on user delete: a departed cursor-holder simply means the
    next pick starts from the top of the rotation, which is the right answer, not
    an error. CASCADE on the team: the rotation is meaningless once the team is gone.
    """

    __tablename__ = "team_assignment_cursors"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    last_assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


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


class AutomationRun(Base):
    """One recorded run of an automation (RADD-1266).

    The engine used to build a complete `RunReport` — per node what arrived and
    what left, every planned action with its skip reason, budget drops — and
    throw it away after logging. This keeps it, in the SAME shape the dry run
    returns (`RuleTestResult`), so one renderer serves both and "what did it do
    last night" is answered by the panel that already answers "what would it
    do". Written in the run's own transaction; a dry run never writes one.

    `report` is JSONB rather than columns per node because the graph's shape is
    the automation's business, not the schema's — and the row is read whole.
    """

    __tablename__ = "automation_runs"
    __table_args__ = (
        Index("ix_automation_runs_automation_started", "automation_id", "started_at"),
        Index("ix_automation_runs_started_at", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), index=True
    )
    #: Which trigger node the run started at — a graph may hold several.
    trigger_node_id: Mapped[str] = mapped_column(String(64))
    #: A `RunSource` value.
    source: Mapped[str] = mapped_column(String(16))
    #: The outbox event that started it, when one did; the scheduler's own
    #: synthetic event for a schedule; NULL for a manual run.
    event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), default="")
    started_at: Mapped[datetime]  # naive UTC, like every engine timestamp
    finished_at: Mapped[datetime]
    #: A `RunStatus` value.
    status: Mapped[str] = mapped_column(String(16), index=True)
    #: Who the actions ran as (the author, or the system actor for rows that
    #: predate spec 116). SET NULL: a run outlives the account it acted as.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Keys of the items the trigger handed in, capped — the list view's answer
    #: to "which issues", without opening the report.
    item_keys: Mapped[list[str]] = mapped_column(JSONB, default=list)
    actions_applied: Mapped[int] = mapped_column(Integer, default=0)
    actions_skipped: Mapped[int] = mapped_column(Integer, default=0)
    #: The traceback's last line on a FAILED run; empty otherwise.
    error: Mapped[str] = mapped_column(Text, default="")
    #: The whole `RuleTestResult`, as JSON.
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
