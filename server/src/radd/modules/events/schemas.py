import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from radd.apitypes import UtcDatetime


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: uuid.UUID | None
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    silent: bool
    created_at: UtcDatetime


class ConsumerFailureRead(BaseModel):
    """An event a consumer's handler raised on (RADD-1538)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    consumer: str
    event_id: int
    status: str  # consumer.FailureStatus
    attempts: int
    error: str
    next_attempt_at: UtcDatetime | None
    first_failed_at: UtcDatetime
    last_failed_at: UtcDatetime
    #: Filled by the router from the event row; None when the ledger was pruned.
    event_type: str | None = None
    entity_label: str | None = None


class ReplayResult(BaseModel):
    delivered: bool
    #: The failure as it stands after a replay that failed again.
    failure: ConsumerFailureRead | None = None
