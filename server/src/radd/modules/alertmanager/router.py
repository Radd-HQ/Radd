import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError

from . import service

router = APIRouter(tags=["alertmanager"])

Session = Annotated[AsyncSession, Depends(get_session)]

_BEARER_PREFIX = "Bearer "


@router.post("/integrations/alertmanager")
async def alertmanager_webhook(
    payload: dict[str, Any],
    session: Session,
    token: Annotated[str, Query()] = "",
    authorization: Annotated[str, Header()] = "",
) -> dict[str, int]:
    """Prometheus Alertmanager webhook receiver (spec 47). Auth = the shared
    token (?token= query or Authorization: Bearer), constant-time; writes go
    through the items/comments seams as the system actor."""
    secret = settings.alertmanager_token
    if not secret:
        raise ForbiddenError("alertmanager connector is disabled (RADD_ALERTMANAGER_TOKEN unset)")
    supplied = token or authorization.removeprefix(_BEARER_PREFIX).strip()
    if not hmac.compare_digest(supplied, secret):
        raise ForbiddenError("bad alertmanager token")
    return await service.process(session, payload)
