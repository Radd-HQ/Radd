from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session

# Backward edge (events loads before auth): tolerated for router enforcement only —
# see docs/modules.md. deps/authz are import-light by design.
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import EventRead

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
async def list_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    after: int = Query(0, ge=0, description="Return events with id greater than this offset"),
    limit: int = Query(100, ge=1, le=500),
) -> list[EventRead]:
    # Workspace member and up; the stream itself is instance-wide (trusted consumers).
    await authz.require(session, user, authz.Permission.ITEM_READ)
    return [EventRead.model_validate(e) for e in await service.read_after(session, after, limit)]
