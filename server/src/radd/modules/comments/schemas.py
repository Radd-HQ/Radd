import uuid

from pydantic import BaseModel, Field

from radd.modules.items.schemas import UserRef

from .types import CommentVisibility
from radd.apitypes import UtcDatetime


class CommentAnchor(BaseModel):
    """Where an inline comment points (RADD-726).

    A text-quote selector: the quoted string plus a little context either side.
    `prefix`/`suffix` are what disambiguate a phrase that occurs more than once —
    without them, a comment on the second "see below" would land on the first.
    """

    quote: str = Field(min_length=1, max_length=1000)
    prefix: str = Field(default="", max_length=200)
    suffix: str = Field(default="", max_length=200)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)
    # `internal` requires Permission.COMMENT_READ_INTERNAL on the item's project.
    visibility: CommentVisibility = CommentVisibility.PUBLIC
    # Spec 50: narrow an INTERNAL comment to specific teams (empty = all internal-readers).
    visible_to_teams: list[uuid.UUID] = Field(default_factory=list)
    # Import-only overrides (honored only for callers with project.manage): attribute
    # the comment to its original author and preserve its original timestamp.
    author_id: uuid.UUID | None = None
    created_at: UtcDatetime | None = None
    # RADD-726: present = this is an INLINE comment on the quoted text.
    anchor: CommentAnchor | None = None


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1)
    # Spec 50: None = leave the team allow-list unchanged; a list replaces it.
    visible_to_teams: list[uuid.UUID] | None = None


class CommentReplyCreate(BaseModel):
    """RADD-1246: `visibility` omitted = the thread's own. Under an INTERNAL
    thread a reply is internal whatever is sent (public is refused) and its
    teams may only NARROW the thread's; under a public thread it may go
    internal, to any teams the writer may address."""

    body: str = Field(min_length=1)
    visibility: CommentVisibility | None = None
    visible_to_teams: list[uuid.UUID] = Field(default_factory=list)


class CommentRead(BaseModel):
    id: uuid.UUID
    entity_type: str = "item"  # RADD-717
    entity_id: uuid.UUID
    author: UserRef | None
    body: str
    visibility: CommentVisibility
    visible_to_teams: list[uuid.UUID] = Field(default_factory=list)  # spec 50
    created_at: UtcDatetime
    updated_at: UtcDatetime
    # RADD-726. `anchor` null = an ordinary thread comment.
    anchor: CommentAnchor | None = None
    resolved_at: UtcDatetime | None = None
    resolved_by: uuid.UUID | None = None
    parent_comment_id: uuid.UUID | None = None
    reply_count: int = 0


class CommentPage(BaseModel):
    comments: list[CommentRead]
    older_cursor: str | None = None
