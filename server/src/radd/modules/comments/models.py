import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import CommentParentType, CommentVisibility


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"
    # The read that matters: every comment on one parent, in order.
    __table_args__ = (Index("ix_comments_parent_order", "entity_type", "entity_id", "created_at", "id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # RADD-717: polymorphic parent. No FK, because it points at several tables —
    # which costs the ON DELETE CASCADE the item column had, so each parent's
    # delete path calls `service.delete_for_parent`. An orphaned comment is
    # worse than a slightly noisier delete: it is invisible and undeletable.
    entity_type: Mapped[str] = mapped_column(
        String(30), default=CommentParentType.ITEM.value, server_default=CommentParentType.ITEM.value
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    # CommentVisibility; internal comments require Permission.COMMENT_READ_INTERNAL.
    visibility: Mapped[str] = mapped_column(String(10), default=CommentVisibility.PUBLIC)

    # --- RADD-726: inline, anchored, resolvable -------------------------------
    #: NULL = an ordinary thread comment, which is every comment that exists
    #: today. Set = inline: `{"quote", "prefix", "suffix"}`, a TEXT-QUOTE
    #: selector rather than a character offset. An offset is invalidated by the
    #: first edit made anywhere above it, so one inserted paragraph would slide
    #: every comment on the page onto the wrong sentence; a quote is re-located
    #: against the current body on each render. Same reason W3C Web Annotation
    #: stores one.
    anchor: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Resolve, never delete — the argument is often the only surviving record of
    #: why a line reads the way it does.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


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
