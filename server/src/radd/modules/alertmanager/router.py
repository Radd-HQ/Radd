from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Prometheus Alertmanager webhook receiver (spec 47, RADD-1317). Auth = a
    RECEIVER's token (?token= or Authorization: Bearer), constant-time; the
    receiver names the project its alerts become issues in."""
    supplied = token or authorization.removeprefix(_BEARER_PREFIX).strip()
    receiver = await service.receiver_for_token(session, supplied)
    if receiver is None:
        # Nothing configured, a wrong token, or an inactive receiver: one answer.
        raise ForbiddenError("bad alertmanager token")
    return await service.process(session, receiver, payload)
