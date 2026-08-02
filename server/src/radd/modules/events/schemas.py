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
