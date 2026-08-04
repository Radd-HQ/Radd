import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Team(Base, TimestampMixin):
    """A Radd grouping with an owner and a purpose — LOCAL, always (RADD-829).

    The directory columns (`directory_group_dn`/`_name`, `source`,
    `directory_missing_since`) retired with `TeamSource`: a team is never
    directory-mirrored any more. The directory's truth lives in the `groups`
    module, and a team reaches it by holding a GROUP as a member.
    """

    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
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
    directory sync that drops the person from an underlying AD group.

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
    """One member of a team: a USER or a GROUP (RADD-829 — polymorphic, exactly
    one side set, surrogate PK). `MemberSource` retired with the rebuild: a
    user row is by definition manual (the sync never writes here any more) and
    a group row IS the directory's presence — the flag had nothing left to say.
    """

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
