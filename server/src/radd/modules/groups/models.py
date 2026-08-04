"""Directory groups (RADD-829): AD objects mirrored WITH their nesting.

The spec-115 D5 split: a Team is a Radd grouping (owner, purpose, project
attachments); a Group is the directory's truth. The old model linked an AD
group TO a team (`teams.directory_group_dn` + `TeamSource`), flattening the
directory's nesting into a link — one concept doing two jobs, decided by a
flag. These tables carry what the link carried (dn, display name, the spec-87
health signal) plus the structure the link threw away.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Group(Base, TimestampMixin):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("dn", name="uq_groups_dn"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: The directory's identity. Unique — one row per AD group, ever.
    dn: Mapped[str] = mapped_column(Text)
    #: Display name (the CN at import; renameable-in-AD, refreshed by sync).
    #: Groups have their OWN namespace — a group and a team may share a name.
    name: Mapped[str] = mapped_column(String(200))
    #: Spec 87's health signal, moved to where it belongs: when the DN stopped
    #: resolving in AD (NULL = healthy). While set, sync paths refuse REMOVALS —
    #: a renamed/deleted group must not read as "everyone left". A vanished
    #: group keeps its grants and is flagged; deleting them automatically would
    #: turn a directory outage into a permission outage.
    directory_missing_since: Mapped[datetime | None] = mapped_column()


class GroupParent(Base):
    """One nesting edge: `child` is a member of `parent`. A GRAPH, not a tree —
    AD allows cycles, so every walk over this table carries a cycle guard and a
    depth limit (service.py), on day one rather than after an incident."""

    __tablename__ = "group_parents"

    child_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )


class GroupMember(Base):
    """A USER's direct membership of one group — wholly sync-owned (there is no
    `source` column because there is no manual path: a group is never local)."""

    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
