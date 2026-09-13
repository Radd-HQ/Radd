import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.choices import ChoiceRead
from radd.apitypes import TOTAL_COUNT_HEADER
from radd.modules.auth import authz
from radd.modules.auth.deps import Actor, CurrentUser
from radd.modules.projects import service as projects_service

from . import pipeline, service
from .schemas import ReleaseCreate, ReleaseRead, ReleaseUpdate

router = APIRouter(prefix="/releases", tags=["releases"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _require(
    session: AsyncSession, user: CurrentUser, project_id: uuid.UUID, permission: authz.Permission
) -> None:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, permission, project=project)


@router.get("/options", response_model=list[ChoiceRead])
async def option_choices(
    session: Session, user: Actor, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    value: Annotated[str | None, Query(max_length=200)] = None,
    project_id: uuid.UUID | None = None,
) -> list[ChoiceRead]:
    rows, total = await service.list_options(session, user, q=q, limit=limit,
        offset=offset, value=value, project_id=project_id)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@router.post("", response_model=ReleaseRead, status_code=201)
async def create_release(data: ReleaseCreate, session: Session, user: CurrentUser) -> ReleaseRead:
    await _require(session, user, data.project_id, authz.Permission.RELEASE_CREATE)
    return ReleaseRead.model_validate(
        await service.create_release(session, data, actor_id=user.id)
    )


@router.get("", response_model=list[ReleaseRead])
async def list_releases(
    project_id: uuid.UUID, session: Session, user: Actor
) -> list[ReleaseRead]:
    await _require(session, user, project_id, authz.Permission.ITEM_READ)
    return [ReleaseRead.model_validate(r) for r in await service.list_releases(session, project_id)]


@router.get("/{release_id}", response_model=ReleaseRead)
async def get_release(release_id: uuid.UUID, session: Session, user: Actor) -> ReleaseRead:
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


@router.post("/{release_id}/sweep")
async def sweep_release(release_id: uuid.UUID, session: Session, user: CurrentUser) -> dict:
    """Ship everything waiting (spec 112). The same operation the release webhook
    performs, on demand — so the pipeline works on an instance with no Forgejo at
    all, and a missed webhook is one button rather than forty manual edits."""
    release = await service.get_release(session, release_id)
    project = await projects_service.get_project(session, release.project_id)
    await authz.require(session, user, authz.Permission.RELEASE_UPDATE, project=project)
    moved = await pipeline.sweep(session, project, release)
    return {"release": release.version, "items_shipped": moved}
