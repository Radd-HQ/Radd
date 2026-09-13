import uuid

from pydantic import BaseModel

from .types import CollabRole


class CollabJoin(BaseModel):
    role: CollabRole


class CollabJoinRead(BaseModel):
    """`session` is the id the socket presents (`?session=`). `seed` is true for
    exactly one editor while the room's document is empty: that client seeds
    the document from the page's markdown; everyone else waits for sync."""

    session: uuid.UUID
    role: CollabRole
    seed: bool
    page_version: int
