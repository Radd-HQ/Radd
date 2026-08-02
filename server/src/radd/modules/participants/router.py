import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import ItemParticipantsRead, ParticipantAdd, ParticipantRow

router = APIRouter(tags=["participants"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/items/{item_id}/participants", response_model=ItemParticipantsRead)
async def list_participants(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> ItemParticipantsRead:
    """Hydrated participant users/teams + grant rows (item.read); `can_manage`
    is computed per actor server-side (item.update OR the item's reporter)."""
    return await service.list_participants(session, item_id, user)


@router.post(
    "/items/{item_id}/participants", response_model=ParticipantRow, status_code=201
)
async def add_participant(
    item_id: uuid.UUID, data: ParticipantAdd, session: Session, user: CurrentUser
) -> ParticipantRow:
    """Add one user OR team (item.update or reporter — 403). Subject outside the
    unknown/inactive user or team / duplicate → 409. Direct users are auto-watched."""
    return await service.add_participant(session, item_id, data, user)


@router.delete("/items/{item_id}/participants/{participant_id}", status_code=204)
async def remove_participant(
    item_id: uuid.UUID, participant_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    """Same gate as add, PLUS a direct user participant may remove THEMSELF."""
    await service.remove_participant(session, item_id, participant_id, user)
