import uuid

from pydantic import BaseModel, ConfigDict, Field
from radd.apitypes import UtcDatetime


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class LabelUpdate(BaseModel):
    """PATCH /labels/{id} (spec 87) — rename/recolor. Renaming is instant across
    every item that carries the label (items reference it by id)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class LabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str | None
    created_at: UtcDatetime
