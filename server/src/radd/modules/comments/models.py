import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import CommentVisibility


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
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
