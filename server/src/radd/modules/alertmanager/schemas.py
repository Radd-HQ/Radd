import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ReceiverCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    token: str = Field(min_length=8, max_length=200)
    project_id: uuid.UUID | None = None
    active: bool = True


class ReceiverUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    #: Empty keeps the stored token.
    token: str | None = Field(default=None, max_length=200)
    project_id: uuid.UUID | None = None
    active: bool | None = None


class ReceiverRead(BaseModel):
    """The token is never returned — only whether one is set."""

    id: uuid.UUID
    name: str
    project_id: uuid.UUID | None
    active: bool
    has_token: bool
    created_at: datetime
