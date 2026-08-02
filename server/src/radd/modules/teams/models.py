import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import MemberSource, TeamSource


class Team(Base, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    # Spec 84: linked AD group (nested membership honored via the transitive
    # matching rule). NULL = not directory-linked; the CN is kept for display.
    directory_group_dn: Mapped[str | None] = mapped_column(Text)
    directory_group_name: Mapped[str | None] = mapped_column(String(200))
    # Spec 87: when the linked group stopped resolving in AD (NULL = healthy).
    # Set by the periodic reconcile, cleared the moment the group answers again.
    # While set, BOTH sync paths refuse to remove anyone — otherwise a renamed or
    # deleted group reads as "everyone left" and quietly revokes the team's access,
    # the periodic loop draining it at once and the login path one person at a time.
    directory_missing_since: Mapped[datetime | None] = mapped_column()
    # Spec 87 (TeamSource): who owns MEMBERSHIP. Kept in lockstep with the link —
    # `directory` exactly when directory_group_dn is set — but modelled as a
    # first-class state rather than a null check, because "membership is
    # read-only here" is a behavior, not an absent field.
    source: Mapped[str] = mapped_column(
        String(20), default=TeamSource.LOCAL, server_default=TeamSource.LOCAL.value
    )
    # Spec 87: the person accountable for the team (the spec-57 ownership idiom).
    # NULL on pre-87 rows — those fall back to the team.update atom, so an
    # ownerless team is still administrable.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class TeamManager(Base):
    """Delegated per-team management (spec 87): a "team leader" who administers
    THIS team and no other.

    A manager need not be a member — a department lead may own a team they are
    not in — and the row is independent of `team_members`, so it survives a
    directory sync that drops the person from the underlying AD group.

    Managers rename the team and manage its membership. They do NOT appoint other
    managers, transfer ownership, delete the team, or attach it to projects: what
    a team may DO on a project is `member.create` there, held by project admins.
    That split is the safety property — a team leader decides who is on their
    team, never what their team is entitled to.
    """

    __tablename__ = "team_managers"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Spec 84 (MemberSource): directory sync owns ONLY its own rows — a manual
    # row for the same user blocks a duplicate directory add (shared PK) and
    # survives every reconcile.
    source: Mapped[str] = mapped_column(
        String(20), default=MemberSource.MANUAL, server_default=MemberSource.MANUAL.value
    )


class ProjectTeam(Base):
    """Team ↔ project attachment granting a role (`roles` table, auth module — spec 06)."""

    __tablename__ = "project_teams"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))  # RESTRICT on delete
