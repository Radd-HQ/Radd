import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser
from radd.modules.items.schemas import ItemRead

from . import service
from .schemas import FormCreate, FormRead, FormSharingUpdate, FormSubmit, FormUpdate

router = APIRouter(prefix="/forms", tags=["forms"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=FormRead, status_code=201)
async def create_form(data: FormCreate, session: Session, user: CurrentUser) -> FormRead:
    return await service.create_form(session, data, actor=user)


@router.get("", response_model=list[FormRead])
async def list_forms(
    project_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[FormRead]:
    return await service.list_forms(session, project_id, actor=user)


@router.get("/{form_id}", response_model=FormRead)
async def get_form(form_id: uuid.UUID, session: Session, user: CurrentUser) -> FormRead:
    """Render a form for submission — open to ITEM_CREATE on the form's project."""
    return await service.render_form(session, form_id, actor=user)


@router.patch("/{form_id}", response_model=FormRead)
async def update_form(
    form_id: uuid.UUID, data: FormUpdate, session: Session, user: CurrentUser
) -> FormRead:
    return await service.update_form(session, form_id, data, actor=user)


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
