import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import service
from .schemas import ItemCsatRead

router = APIRouter(tags=["csat"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/items/{item_id}/csat", response_model=ItemCsatRead)
async def item_csat(item_id: uuid.UUID, session: Session, user: CurrentUser) -> ItemCsatRead:
    """The item's ANSWERED satisfaction survey (spec 65) — 404 both when no
    survey was ever sent and while it is still unanswered (the rail chip is
    404-quiet and appears only once the requester responds)."""
    await items_service.require_readable_item(session, item_id, user)
    survey = await service.responded_survey(session, item_id)
    assert survey.rating is not None and survey.responded_at is not None  # narrowed
    return ItemCsatRead(
        rating=survey.rating, comment=survey.comment, responded_at=survey.responded_at
    )
