import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class StateCategoryDef(Base, TimestampMixin):
    """The user-owned classification tier over states. Name, colour and order are
    the operator's; `behaves_as` (a fixed StateCategory) is what reports, sweeps and
    guards read. The six builtins are seeded as editable rows (key = the enum value)
    and keep their behaves_as; keys are immutable because states reference them."""

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
    # The vocabulary row classifying this state; `category` is derived from its
    # behaves_as at assignment time so consumers read a plain enum column.
    category_key: Mapped[str] = mapped_column(
        ForeignKey("state_categories.key"), default="todo"
    )


class WorkflowTransition(Base, TimestampMixin):
    """One guarded edge of a project's transition graph (spec 61).

    `from_state_id` NULL = the wildcard (applies from any source state). Several
    rows may share an edge, scoped by `applies_when` and resolved first-match.
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
    # A published release performs this move for every item in from_state_id,
    # recording the release. Requires a from-state.
    on_release: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
