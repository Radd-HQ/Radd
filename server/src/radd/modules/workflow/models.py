import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class StateCategoryDef(Base, TimestampMixin):
    """The ONE user-owned classification tier over states (RADD-854 — the
    consolidation of RADD-851/852's two half-tiers). A row is vocabulary:
    name, colour, order are the operator's. `behaves_as` is the semantic
    anchor — one of the six fixed `StateCategory` behaviours — which is what
    lets every report/sweep/guard keep working untouched by whatever words an
    instance invents. The six builtins are seeded as EDITABLE rows (key = the
    enum value, behaves_as = itself): rename Todo to Ready and boards say
    Ready while throughput still counts todo-like work. Keys are immutable
    (they are the reference states carry); builtins keep their behaves_as and
    cannot be deleted."""

    __tablename__ = "state_categories"
    __table_args__ = (UniqueConstraint("key"), UniqueConstraint("name"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)  # hex, optional
    position: Mapped[int] = mapped_column(Integer, default=0)
    behaves_as: Mapped[str] = mapped_column(String(20))  # StateCategory value
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class State(Base, TimestampMixin):
    __tablename__ = "states"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # RADD-854: which VOCABULARY row classifies this state. `category` above
    # is DERIVED-but-stored from the row's behaves_as at assignment time, so
    # the 21 semantic consumers keep reading a plain enum column.
    category_key: Mapped[str] = mapped_column(
        ForeignKey("state_categories.key"), default="todo"
    )


class WorkflowTransition(Base, TimestampMixin):
    """One guarded edge of a project's transition graph (spec 61).

    `from_state_id` NULL = the wildcard (applies from any source state), which is
    why (project, from, to) uniqueness is an app-level check, not a DB constraint.
    """

    __tablename__ = "workflow_transitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    from_state_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("states.id"))
    to_state_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("states.id"))
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # [{check, params}]
    # Spec 107 follow-up: bare field-condition dicts ({kind, key, op, values?,
    # display?, type?}) scoping WHICH items this row governs — empty = every
    # item. Resolution is FIRST-MATCH (see transitions.governing_row).
    applies_when: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    position: Mapped[int] = mapped_column(Integer)
