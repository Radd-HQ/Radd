import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class State(Base, TimestampMixin):
    __tablename__ = "states"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


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
