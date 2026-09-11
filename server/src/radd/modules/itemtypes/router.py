import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.choices import ChoiceRead
from radd.apitypes import TOTAL_COUNT_HEADER
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import service
from .schemas import IssueTypeCreate, IssueTypeRead, IssueTypeUpdate

router = APIRouter(prefix="/issue-types", tags=["itemtypes"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/options", response_model=list[ChoiceRead])
async def option_choices(
    session: Session, user: CurrentUser, response: Response,
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


@router.post("", response_model=IssueTypeRead, status_code=201)
async def create_type(data: IssueTypeCreate, session: Session, user: CurrentUser) -> IssueTypeRead:
    project = await projects_service.get_project(session, data.project_id)
    await authz.require(session, user, authz.Permission.ISSUE_TYPE_CREATE, project=project)
    return IssueTypeRead.model_validate(await service.create_type(session, data, actor_id=user.id))


@router.get("", response_model=list[IssueTypeRead])
async def list_types(
    project_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[IssueTypeRead]:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    return [IssueTypeRead.model_validate(t) for t in await service.list_types(session, project_id)]


@router.patch("/{type_id}", response_model=IssueTypeRead)
async def update_type(
    type_id: uuid.UUID, data: IssueTypeUpdate, session: Session, user: CurrentUser
) -> IssueTypeRead:
    issue_type = await service.get_type(session, type_id)
    project = await projects_service.get_project(session, issue_type.project_id)
    await authz.require(session, user, authz.Permission.ISSUE_TYPE_UPDATE, project=project)
    return IssueTypeRead.model_validate(
        await service.update_type(session, type_id, data, actor_id=user.id)
    )


@router.delete("/{type_id}", status_code=204)
async def delete_type(type_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    issue_type = await service.get_type(session, type_id)
    project = await projects_service.get_project(session, issue_type.project_id)
    await authz.require(session, user, authz.Permission.ISSUE_TYPE_DELETE, project=project)
    await service.delete_type(session, type_id, actor_id=user.id)
