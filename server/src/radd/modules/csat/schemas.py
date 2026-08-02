from pydantic import BaseModel, Field

from radd.apitypes import UtcDatetime

from .types import COMMENT_MAX_CHARS, RATING_MAX, RATING_MIN


class PublicCsatRead(BaseModel):
    """The public rating page's render payload — the token is the credential, so
    only the item's key/title and the survey's current answer are exposed."""

    item_key: str
    item_title: str
    rating: int | None
    responded_at: UtcDatetime | None


class PublicCsatSubmit(BaseModel):
    rating: int = Field(ge=RATING_MIN, le=RATING_MAX)
    comment: str = Field(default="", max_length=COMMENT_MAX_CHARS)


class ItemCsatRead(BaseModel):
    """The responded survey on an item (issue-rail chip) — 404 until responded."""

    rating: int
    comment: str
    responded_at: UtcDatetime
