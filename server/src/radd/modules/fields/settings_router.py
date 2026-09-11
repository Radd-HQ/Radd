"""Bounded settings reads; complete field registries retain their existing API."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.apitypes import TOTAL_COUNT_HEADER
from radd.choices import ChoiceRead
from radd.db import get_session
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.types import Permission

from . import directory
from .schemas import (
    FieldManagementRead,
    FieldProjectReferences,
    FieldSettingsSummaryRead,
    FieldSummaryRead,
)

router = APIRouter(prefix="/fields", tags=["fields"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/settings-summary", response_model=FieldSettingsSummaryRead)
async def summary(session: Session, user: CurrentUser):
    return await directory.summary(session, user)


@router.get("/directory", response_model=list[FieldSummaryRead])
async def page(
    response: Response,
    session: Session,
    user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await directory.page(session, user, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@router.get("/definitions/{identifier}", response_model=FieldManagementRead)
async def definition(
    identifier: uuid.UUID, session: Session, user: CurrentUser, include_options: bool = True,
):
    return await directory.by_id(session, user, identifier, include_options=include_options)


@router.get("/definitions/{identifier}/options", response_model=list[str])
async def option_page(
    identifier: uuid.UUID,
    response: Response,
    session: Session,
    user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    exclude: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await directory.option_page(
        session, user, identifier, q=q, exclude=exclude, limit=limit, offset=offset,
    )
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@router.get("/scope-projects/options", response_model=list[ChoiceRead])
async def project_choices(
    response: Response,
    session: Session,
    user: CurrentUser,
    permission: Literal[Permission.FIELD_CREATE, Permission.FIELD_UPDATE, Permission.FIELD_MANAGE],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await directory.project_choices(
        session, user, permission, q=q, limit=limit, offset=offset
    )
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@router.post("/scope-projects/references", response_model=list[ChoiceRead])
async def project_references(data: FieldProjectReferences, session: Session, user: CurrentUser):
    return await directory.project_references(session, user, data.ids)
