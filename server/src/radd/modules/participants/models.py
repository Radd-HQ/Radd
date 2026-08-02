import uuid

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ItemParticipant(Base, TimestampMixin):
    """One participant grant on an item (spec 72): exactly one of user_id /
    team_id (the `view_shares` idiom, here DB-enforced by the CHECK). A USER row
    is a direct participant — auto-watched on add, so the ordinary watcher
    fan-out reaches them. A TEAM row stays LIVE: the notify consumer resolves
    CURRENT membership at fan-out time, so joining a team joins its shared
    tickets and leaving stops delivery without cleanup rows. Rows die with the
    item/user/team (FK CASCADE); user-merge dedupes like view_shares
    (auth `_MERGE_DEDUPE` + `added_by` repoint)."""

    __tablename__ = "item_participants"
    __table_args__ = (
        # Naming convention prefixes ck_<table>_ — final name
        # ck_item_participants_one_subject.
        CheckConstraint(
            "(user_id IS NULL) != (team_id IS NULL)",
            name="one_subject",
        ),
        UniqueConstraint("item_id", "user_id"),
        UniqueConstraint("item_id", "team_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
