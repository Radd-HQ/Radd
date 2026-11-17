import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from radd import outbound

from .types import DeliveryStatus
from radd.apitypes import UtcDatetime


def _checked(url: str) -> str:
    """Refuse at save what the server would refuse to call (RADD-1546): a
    loopback, private or link-local address. A NAME is judged when it is
    resolved, at delivery."""
    try:
        outbound.check_url(url)
    except outbound.OutboundRefused as error:
        raise ValueError(str(error)) from error
    return url


class EndpointCreate(BaseModel):
    url: str = Field(pattern=r"^https?://", max_length=1000)
    description: str = Field(default="", max_length=500)
    event_types: list[str] | None = None  # None = subscribe to everything

    @field_validator("url")
    @classmethod
    def _callable(cls, value: str) -> str:
        return _checked(value)


class EndpointUpdate(BaseModel):
    url: str | None = Field(default=None, pattern=r"^https?://", max_length=1000)
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str] | None = None
    active: bool | None = None

    @field_validator("url")
    @classmethod
    def _callable(cls, value: str | None) -> str | None:
        return value if value is None else _checked(value)


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
