import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import AuditEntry

router = APIRouter(prefix="/audit", tags=["audit"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[AuditEntry])
async def audit_log(
    session: Session,
    user: CurrentUser,
    entity_type: str | None = None,
    event_type: Annotated[list[str] | None, Query(description="event type(s); repeatable")] = None,
    actor_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[AuditEntry]:
    """The instance-wide audit trail — every attributable change, newest first.
    Admin-gated (spec 86: the workspace scope is gone)."""
    return await service.audit_log(
        session,
        actor=user,
        entity_type=entity_type,
        event_types=event_type,
        actor_id=actor_id,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
