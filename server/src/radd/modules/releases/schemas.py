import uuid

from pydantic import BaseModel, ConfigDict, Field

from .types import ReleaseStatus
from radd.apitypes import UtcDatetime


class ReleaseCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    status: ReleaseStatus = ReleaseStatus.PLANNED
    description: str = ""


class ReleaseUpdate(BaseModel):
    # Omitted = unchanged. Setting status -> released stamps released_at server-side.
    name: str | None = Field(default=None, min_length=1, max_length=200)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    status: ReleaseStatus | None = None
    description: str | None = None


class ReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: str
    status: ReleaseStatus
    released_at: UtcDatetime | None
    description: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
