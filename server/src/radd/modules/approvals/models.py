import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ApprovalRequest(Base, TimestampMixin):
    """One request to unlock ONE move of an item into `to_state_id` (spec 71;
    per-entry approver rules since spec 107).

    The rule's `approvers` entries ([{kind, id, name, required?}]) are
    SNAPSHOTTED here so editing or deleting the transition rule never mutates
    an in-flight request — only team MEMBERSHIP resolves live at vote time.
    ONE live (pending|approved) request per (item, to_state) is an app-level 409
    (statuses make a partial unique index more trouble than it's worth).
    """

    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    transition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_transitions.id", ondelete="SET NULL"), nullable=True
    )
    approvers: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    to_state_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("states.id"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), index=True)


class ApprovalVote(Base, TimestampMixin):
    """One approver's verdict on a request — a revote while pending REPLACES it."""

    __tablename__ = "approval_votes"
    __table_args__ = (UniqueConstraint("request_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    verdict: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(Text, default="")
