import uuid

from pydantic import BaseModel, Field

from radd.modules.items.schemas import UserRef

from .types import CommentVisibility
from radd.apitypes import UtcDatetime


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


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1)
    # Spec 50: None = leave the team allow-list unchanged; a list replaces it.
    visible_to_teams: list[uuid.UUID] | None = None


class CommentRead(BaseModel):
    id: uuid.UUID
    entity_type: str = "item"  # RADD-717
    entity_id: uuid.UUID
    #: The entity id when the parent IS an item, else null — so every existing
    #: issue-side consumer keeps working unchanged.
    item_id: uuid.UUID | None
    author: UserRef
    body: str
    visibility: CommentVisibility
    visible_to_teams: list[uuid.UUID] = Field(default_factory=list)  # spec 50
    created_at: UtcDatetime
    updated_at: UtcDatetime
