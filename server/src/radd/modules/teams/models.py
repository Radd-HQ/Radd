import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Team(Base, TimestampMixin):
    """A local grouping with an owner (RADD-829); it reaches the directory by holding a GROUP as a member."""

    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    # Spec 87: the accountable person. NULL only after the owner's account is
    # hard-deleted (RADD-784: ownership awaits a deliberately chosen new owner).
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class TeamManager(Base):
    """Delegated per-team management (spec 87): renames the team and manages its
    membership, nothing more — no appointing managers, transferring or deleting.
    A manager need not be a member, and the row survives a directory sync. The
    safety property: a team leader decides who is on their team, never what the
    team is entitled to (project grants stay with project admins)."""

    __tablename__ = "team_managers"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class TeamMember(Base):
    """One member of a team: a USER or a GROUP (RADD-829; exactly one side set)."""

    __tablename__ = "team_members"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NULL) != (group_id IS NULL)", name="ck_team_members_one_subject"
        ),
        UniqueConstraint("team_id", "user_id", name="uq_team_members_user"),
        UniqueConstraint("team_id", "group_id", name="uq_team_members_group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )


