import uuid
from typing import Any

from pydantic import BaseModel
from radd.apitypes import UtcDatetime


class AuditActor(BaseModel):
    """Who caused the change (resolved from the event's actor_id)."""

    id: uuid.UUID
    name: str
    email: str | None = None


class AuditEntry(BaseModel):
    """One audit-log row — a projection of an append-only event."""

    id: int  # the event offset (monotonic)
    at: UtcDatetime
    actor: AuditActor | None = None
    event_type: str
    entity_type: str
    entity_id: str
    # Field-level diff when the source event carries one (item changes); else None.
    changes: list[dict[str, Any]] | None = None
