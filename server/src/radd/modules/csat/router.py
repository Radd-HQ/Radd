import uuid
from typing import Annotated

from radd.exceptions import NotFoundError
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service

from . import service
from .schemas import ItemCsatRead

router = APIRouter(tags=["csat"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/items/{item_id}/csat", response_model=ItemCsatRead | None)
async def item_csat(item_id: uuid.UUID, session: Session, user: CurrentUser) -> ItemCsatRead | None:
    """The item's ANSWERED satisfaction survey, or null — none sent, or not yet
    answered. RADD-1292: this used to 404 for both, so every issue view logged
    a failed request for the ordinary case of "no survey"; an unreadable item
    still 404s."""
    await items_service.require_readable_item(session, item_id, user)
    try:
        survey = await service.responded_survey(session, item_id)
    except NotFoundError:
        return None
    assert survey.rating is not None and survey.responded_at is not None  # narrowed
    return ItemCsatRead(
        rating=survey.rating, comment=survey.comment, responded_at=survey.responded_at
    )
