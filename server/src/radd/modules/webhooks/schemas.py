import uuid

from pydantic import BaseModel, ConfigDict, Field

from .types import DeliveryStatus
from radd.apitypes import UtcDatetime


class EndpointCreate(BaseModel):
    url: str = Field(pattern=r"^https?://", max_length=1000)
    description: str = Field(default="", max_length=500)
    event_types: list[str] | None = None  # None = subscribe to everything


class EndpointUpdate(BaseModel):
    url: str | None = Field(default=None, pattern=r"^https?://", max_length=1000)
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str] | None = None
    active: bool | None = None


class EndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    secret: str
    description: str
    event_types: list[str] | None
    active: bool
    created_at: UtcDatetime


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint_id: uuid.UUID
    event_id: int
    status: DeliveryStatus
    attempts: int
    next_attempt_at: UtcDatetime
    last_status_code: int | None
    last_error: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
