import uuid
from typing import Any

from pydantic import BaseModel
from radd.apitypes import UtcDatetime


class AuditActor(BaseModel):
    """Who caused the change (resolved from the event's actor_id)."""

    id: uuid.UUID
    name: str
    email: str | None = None


class AuditProject(BaseModel):
    id: uuid.UUID
    key: str
    name: str


class AuditEntry(BaseModel):
    """One audit-log row — a projection of an append-only event (spec 123)."""

    id: int  # the event offset (monotonic)
    at: UtcDatetime
    actor: AuditActor | None = None
    event_type: str
    #: From the registered `EventTypeSpec` — the SPA never hardcodes a label.
    event_label: str
    event_group: str
    entity_type: str
    entity_id: str
    #: The entity's display label at write time (`RADD-123 Board scroll`).
    entity_label: str | None = None
    #: The subject refs the payload carries (`item`, `page`, `page_space`,
    #: `project`…) — what a link to the entity is built from.
    refs: dict[str, Any] = {}
    project: AuditProject | None = None
    automated: bool = False
    silent: bool = False
    # Field-level diff when the source event carries one; else None.
    changes: list[dict[str, Any]] | None = None


class AuditEventType(BaseModel):
    event_type: str
    label: str
    group: str
    entity_type: str
    has_changes: bool
    audited: bool


class AuditEntityType(BaseModel):
    key: str
    label: str


class AuditCatalog(BaseModel):
    """What the registry knows (spec 123): the SPA builds its filters from
    this, never from a hardcoded list that omits every module added since."""

    event_types: list[AuditEventType]
    entity_types: list[AuditEntityType]
