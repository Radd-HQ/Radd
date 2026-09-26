"""Receiver administration (RADD-1317) — admin-level, on the `alertreceiver.*`
atoms; the webhook itself is verified by the receiver's token."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import ReceiverCreate, ReceiverRead, ReceiverUpdate

router = APIRouter(prefix="/alertmanager", tags=["alertmanager"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _read(receiver) -> ReceiverRead:
    return ReceiverRead(
        id=receiver.id, name=receiver.name, project_id=receiver.project_id, active=receiver.active,
        comment_updates=receiver.comment_updates, label=receiver.label, resolve_state_id=receiver.resolve_state_id,
        has_token=bool(receiver.token), created_at=receiver.created_at,
    )


@router.get("/receivers", response_model=list[ReceiverRead])
async def list_receivers(session: Session, user: CurrentUser) -> list[ReceiverRead]:
    await authz.require(session, user, authz.Permission.ALERT_RECEIVER_READ)
    return [_read(r) for r in await service.list_receivers(session)]


@router.post("/receivers", response_model=ReceiverRead, status_code=201)
async def create_receiver(data: ReceiverCreate, session: Session, user: CurrentUser) -> ReceiverRead:
    await authz.require(session, user, authz.Permission.ALERT_RECEIVER_CREATE)
    return _read(await service.create_receiver(session, data, actor_id=user.id))


@router.patch("/receivers/{receiver_id}", response_model=ReceiverRead)
async def update_receiver(
    receiver_id: uuid.UUID, data: ReceiverUpdate, session: Session, user: CurrentUser
) -> ReceiverRead:
    await authz.require(session, user, authz.Permission.ALERT_RECEIVER_UPDATE)
    return _read(await service.update_receiver(session, receiver_id, data, actor_id=user.id))


@router.delete("/receivers/{receiver_id}", status_code=204)
async def delete_receiver(receiver_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await authz.require(session, user, authz.Permission.ALERT_RECEIVER_DELETE)
    await service.delete_receiver(session, receiver_id, actor_id=user.id)
