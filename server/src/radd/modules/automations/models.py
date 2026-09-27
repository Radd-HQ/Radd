import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Automation(Base, TimestampMixin):
    """A graph of nodes and edges (spec 116) run when one of its TRIGGER nodes
    fires. Not called a workflow: `workflow` owns item states. `nodes`/`edges`
    are raw JSON validated on write by `graph.validate` and re-checked on read;
    the typed view is `graph.Node` / `graph.Edge`."""

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
    # predating spec 116 have no author to name; those run as the system actor
    # (RADD-1450). A departed or deactivated owner's identity is RETAINED, not
    # nulled, so that run fails closed instead of quietly becoming the system's.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    #: The CURRENT version's number (RADD-1268). Every save that changes the
    #: graph, the name or the orientation writes an `AutomationVersion` row and
    #: moves this; a toggle of `enabled` does not.
    version: Mapped[int] = mapped_column(Integer, default=1)


class AutomationVersion(Base):
    """One immutable version (RADD-1268). Every save that changes what the
    automation IS writes a row; a restore writes a NEW row copying an old one.
    Unlike `page_versions`, the CURRENT version is stored too, so "what was it at
    v3" is a row, not arithmetic. The live row still holds the current graph."""

    __tablename__ = "automation_versions"
    __table_args__ = (UniqueConstraint("automation_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    nodes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    edges: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    orientation: Mapped[str] = mapped_column(String(16), default="vertical")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime]  # naive UTC
    #: "Why I changed this" — optional, and the one thing a diff cannot say.
    note: Mapped[str] = mapped_column(Text, default="")
    #: The version this one COPIED, when it was made by a restore; NULL for an
    #: ordinary save. The list shows "restored from v3" from it.
    restored_from: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TriggerBinding(Base):
    """One TRIGGER node of a graph, projected into a row so the engine and the
    scheduler can find "who cares about item.created" / due schedules without
    parsing every graph. Rebuilt from the graph on every write; the graph stays
    the source of truth. Not named AutomationTrigger: that is the sentinel enum."""

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
    #: RADD-1315 — the trigger node's "also run on changes made by other
    #: automations" checkbox. Off by default: an automation-caused event reaches
    #: only the triggers that asked for it, below the chain-depth cap.
    include_automated: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)


class ValidationBinding(Base):
    """What one VALIDATE trigger node governs (spec 119) — one row per (trigger,
    target), rebuilt wholesale by `service._sync_validations`, so intake can
    answer "what validates this draft" on the request path without parsing
    graphs. `target_id` has no FK (polymorphic): a deleted target stops matching."""

    __tablename__ = "automation_validations"

    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: A `ValidationTargetKind` value — form | issue_type | project.
    target_kind: Mapped[str] = mapped_column(String(16), primary_key=True, index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, index=True)
    #: A `ValidationMode`: REQUIRED iff this trigger reaches a Block node (RADD-1329).
    mode: Mapped[str] = mapped_column(String(16))


class TeamAssignmentCursor(Base):
    """Round-robin position for `assign_round_robin` (RADD-1044) — ONE row per
    TEAM, so every rule assigning from a team shares the rotation. Advanced in the
    same SAVEPOINT as the assignment it records. SET NULL on user delete (the next
    pick starts from the top); CASCADE on the team."""

    __tablename__ = "team_assignment_cursors"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    last_assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AutomationScheduleState(Base):
    """Scheduler bookkeeping per scheduled TRIGGER node (a graph may have two
    clocks). Advanced in the same transaction that emits `automation.scheduled`:
    at-most-once per occurrence; a missed window fires once, never a backlog."""

    __tablename__ = "automation_schedule_state"

    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automations.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_run_at: Mapped[datetime]  # naive UTC, like every engine timestamp
    last_run_at: Mapped[datetime | None]


class AutomationRun(Base):
    """One recorded run (RADD-1266), stored in the dry run's `RuleTestResult`
    shape so one panel renders both. Written in the run's own transaction; a dry
    run never writes one. `report` is JSONB because the graph's shape is the
    automation's business."""

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
