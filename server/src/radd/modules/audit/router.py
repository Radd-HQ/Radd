import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser
from radd.modules.events.types import EventSource

from . import service
from .schemas import AuditCatalog, AuditEntry

router = APIRouter(prefix="/audit", tags=["audit"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/catalog", response_model=AuditCatalog)
async def audit_catalog(user: CurrentUser) -> AuditCatalog:
    """The event and entity vocabulary the filters are built from (spec 123) —
    what the kernel registry knows, so a module added tomorrow appears here
    with no SPA edit. Labels only; nothing here is a secret."""
    return service.catalog()


@router.get("", response_model=list[AuditEntry])
async def audit_log(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_type: Annotated[list[str] | None, Query(description="event type(s); repeatable")] = None,
    actor_id: uuid.UUID | None = None,
    changed_field: str | None = None,
    source: EventSource | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    q: str | None = None,
    include_noise: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[AuditEntry]:
    """The audit trail — every attributable change, newest first (spec 123).

    An instance admin reads the whole instance; anyone else must pass
    `project_id` for a project they hold `project.manage` on, and reads only
    that project's rows. `q` is trigram-indexed free text over the event, the
    entity and the changed values; `changed_field` matches rows whose diff
    touched that field; machine noise (`audited=False` event types) is hidden
    unless `include_noise`.
    """
    return await service.audit_log(
        session,
        actor=user,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_types=event_type,
        actor_id=actor_id,
        changed_field=changed_field,
        source=source,
        start=start,
        end=end,
        q=q,
        include_noise=include_noise,
        limit=limit,
        offset=offset,
    )
