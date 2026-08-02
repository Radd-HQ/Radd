import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import service
from .schemas import ReleaseCreate, ReleaseRead, ReleaseUpdate

router = APIRouter(prefix="/releases", tags=["releases"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _require(
    session: AsyncSession, user: CurrentUser, project_id: uuid.UUID, permission: authz.Permission
) -> None:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, permission, project=project)


@router.post("", response_model=ReleaseRead, status_code=201)
async def create_release(data: ReleaseCreate, session: Session, user: CurrentUser) -> ReleaseRead:
    await _require(session, user, data.project_id, authz.Permission.RELEASE_CREATE)
    return ReleaseRead.model_validate(
        await service.create_release(session, data, actor_id=user.id)
    )


@router.get("", response_model=list[ReleaseRead])
async def list_releases(
    project_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[ReleaseRead]:
    await _require(session, user, project_id, authz.Permission.ITEM_READ)
    return [ReleaseRead.model_validate(r) for r in await service.list_releases(session, project_id)]


@router.get("/{release_id}", response_model=ReleaseRead)
async def get_release(release_id: uuid.UUID, session: Session, user: CurrentUser) -> ReleaseRead:
    release = await service.get_release(session, release_id)
    await _require(session, user, release.project_id, authz.Permission.ITEM_READ)
    return ReleaseRead.model_validate(release)


@router.patch("/{release_id}", response_model=ReleaseRead)
async def update_release(
    release_id: uuid.UUID, data: ReleaseUpdate, session: Session, user: CurrentUser
) -> ReleaseRead:
    release = await service.get_release(session, release_id)
    await _require(session, user, release.project_id, authz.Permission.RELEASE_UPDATE)
    return ReleaseRead.model_validate(
        await service.update_release(session, release_id, data, actor_id=user.id)
    )


@router.delete("/{release_id}", status_code=204)
async def delete_release(release_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    release = await service.get_release(session, release_id)
    await _require(session, user, release.project_id, authz.Permission.RELEASE_DELETE)
    await service.delete_release(session, release_id, actor_id=user.id)
