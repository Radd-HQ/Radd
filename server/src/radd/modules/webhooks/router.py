import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import DeliveryRead, EndpointCreate, EndpointRead, EndpointUpdate


def _read(endpoint) -> EndpointRead:
    # The stored secret is ciphertext (RADD-1086); the admin surface shows the
    # signing value the receiver must be configured with.
    return EndpointRead.model_validate(endpoint).model_copy(
        update={"secret": service.reveal_secret(endpoint)}
    )

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Endpoints carry signing secrets, so everything here is admin-level (project.manage).


@router.post("", response_model=EndpointRead, status_code=201)
async def create_endpoint(data: EndpointCreate, session: Session, user: CurrentUser) -> EndpointRead:
    await authz.require(session, user, authz.Permission.WEBHOOK_CREATE)
    endpoint = await service.create_endpoint(session, data, actor_id=user.id)
    return _read(endpoint)


@router.get("", response_model=list[EndpointRead])
async def list_endpoints(session: Session, user: CurrentUser) -> list[EndpointRead]:
    await authz.require(session, user, authz.Permission.WEBHOOK_MANAGE)
    return [_read(e) for e in await service.list_endpoints(session)]


@router.patch("/{endpoint_id}", response_model=EndpointRead)
async def update_endpoint(
    endpoint_id: uuid.UUID, data: EndpointUpdate, session: Session, user: CurrentUser
) -> EndpointRead:
    endpoint = await service.get_endpoint(session, endpoint_id)
    await authz.require(
        session, user, authz.Permission.WEBHOOK_UPDATE
    )
    endpoint = await service.update_endpoint(session, endpoint_id, data, actor_id=user.id)
    return _read(endpoint)


@router.delete("/{endpoint_id}", status_code=204)
async def delete_endpoint(endpoint_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Delete an endpoint and its delivery log (spec 87)."""
    await authz.require(session, user, authz.Permission.WEBHOOK_DELETE)
    await service.delete_endpoint(session, endpoint_id, actor_id=user.id)


@router.get("/{endpoint_id}/deliveries", response_model=list[DeliveryRead])
async def list_deliveries(
    endpoint_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
) -> list[DeliveryRead]:
    endpoint = await service.get_endpoint(session, endpoint_id)
    await authz.require(
        session, user, authz.Permission.WEBHOOK_MANAGE
    )
    return [
        DeliveryRead.model_validate(d)
        for d in await service.list_deliveries(session, endpoint_id, limit)
    ]
