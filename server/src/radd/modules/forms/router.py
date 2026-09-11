import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.choices import ChoiceRead
from radd.apitypes import TOTAL_COUNT_HEADER
from radd.modules.auth.deps import CurrentUser
from radd.modules.items.schemas import ItemRead

from . import service, sharing
from .schemas import FormCreate, FormRead, FormSharingUpdate, FormSubmit, FormUpdate, FormShareEntry, FormShareRead, FormShareDirectoryRead
from .types import FormShareSubject

router = APIRouter(prefix="/forms", tags=["forms"])

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


@router.post("", response_model=FormRead, status_code=201)
async def create_form(data: FormCreate, session: Session, user: CurrentUser) -> FormRead:
    return await service.create_form(session, data, actor=user)


@router.get("", response_model=list[FormRead])
async def list_forms(
    project_id: uuid.UUID, session: Session, user: CurrentUser, include_shares: bool = True
) -> list[FormRead]:
    return await service.list_forms(session, project_id, actor=user, include_shares=include_shares)


@router.get("/{form_id}", response_model=FormRead)
async def get_form(form_id: uuid.UUID, session: Session, user: CurrentUser) -> FormRead:
    """Render a form for submission — open to ITEM_CREATE on the form's project."""
    return await service.render_form(session, form_id, actor=user)


@router.patch("/{form_id}", response_model=FormRead)
async def update_form(
    form_id: uuid.UUID, data: FormUpdate, session: Session, user: CurrentUser, include_shares: bool = True
) -> FormRead:
    return await service.update_form(session, form_id, data, actor=user, include_shares=include_shares)


@router.put("/{form_id}/sharing", response_model=FormRead)
async def update_sharing(
    form_id: uuid.UUID, data: FormSharingUpdate, session: Session, user: CurrentUser
) -> FormRead:
    """Replace the form's FULL portal share list (spec 73) — form.manage."""
    return await service.update_sharing(session, form_id, data, actor=user)


@router.delete("/{form_id}", status_code=204)
async def delete_form(form_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_form(session, form_id, actor=user)


@router.post("/{form_id}/submit", response_model=ItemRead, status_code=201)
async def submit_form(
    form_id: uuid.UUID, data: FormSubmit, session: Session, user: CurrentUser
) -> ItemRead:
    """Submit the form: creates a work item in its project (defaults + validated values)."""
    return await service.submit_form(session, form_id, data, actor=user)


@router.get("/{form_id}/sharing", response_model=list[FormShareDirectoryRead])
async def share_directory(form_id: uuid.UUID, session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await sharing.directory(session, form_id, user, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@router.get("/{form_id}/sharing/candidates", response_model=list[ChoiceRead])
async def share_candidates(form_id: uuid.UUID, kind: FormShareSubject, session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await sharing.candidates(session, form_id, user, kind, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@router.post("/{form_id}/sharing", response_model=FormShareRead, status_code=201)
async def add_share(form_id: uuid.UUID, data: FormShareEntry, session: Session, user: CurrentUser):
    return await sharing.add(session, form_id, data, user)


@router.delete("/{form_id}/sharing/{share_id}", status_code=204)
async def remove_share(form_id: uuid.UUID, share_id: uuid.UUID, session: Session, user: CurrentUser):
    await sharing.remove(session, form_id, share_id, user)
