import uuid

from pydantic import BaseModel, ConfigDict, Field
from radd.apitypes import UtcDatetime


class CannedResponseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    position: int = 0


class CannedResponseUpdate(BaseModel):
    # Omitted = unchanged.
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1)
    position: int | None = None


class CannedRenderResult(BaseModel):
    """GET /canned-responses/{id}/render?item_id= — the body with its `{{token}}`
    variables resolved against that item (spec 66)."""

    body: str


class CannedResponseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    position: int
    created_at: UtcDatetime
    updated_at: UtcDatetime
