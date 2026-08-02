import uuid

from pydantic import BaseModel, ConfigDict, Field

from .types import WebLinkCategory
from radd.apitypes import UtcDatetime


class WebLinkCreate(BaseModel):
    # item_id comes from the URL path, not the body.
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field("", max_length=300)
    category: WebLinkCategory = WebLinkCategory.EXTERNAL


class WebLinkUpdate(BaseModel):
    # Omitted = unchanged.
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    category: WebLinkCategory | None = None


class WebLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    url: str
    title: str
    category: WebLinkCategory
    created_by: uuid.UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
