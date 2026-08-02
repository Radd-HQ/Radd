import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import CommentParentType, CommentVisibility


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"
    # The read that matters: every comment on one parent, in order.
    __table_args__ = (Index("ix_comments_parent", "entity_type", "entity_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # RADD-717: polymorphic parent. No FK, because it points at several tables —
    # which costs the ON DELETE CASCADE the item column had, so each parent's
    # delete path calls `service.delete_for_parent`. An orphaned comment is
    # worse than a slightly noisier delete: it is invisible and undeletable.
    entity_type: Mapped[str] = mapped_column(
        String(30), default=CommentParentType.ITEM.value, server_default=CommentParentType.ITEM.value
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    # CommentVisibility; internal comments require Permission.COMMENT_READ_INTERNAL.
    visibility: Mapped[str] = mapped_column(String(10), default=CommentVisibility.PUBLIC)


class CommentVisibilityTeam(Base):
    """Spec 50: an internal comment may be narrowed to specific team(s). No rows =
    visible to every COMMENT_READ_INTERNAL holder (the pre-spec-50 default); rows
    narrow it to members of the named teams (author + project managers still see)."""

    __tablename__ = "comment_visibility_teams"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
