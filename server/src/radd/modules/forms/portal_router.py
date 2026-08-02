"""Authenticated requester-portal router (spec 73). ANY signed-in user may call
these — eligibility (public OR shared with the actor/their teams) is the only
gate, checked per form in portal.py; ineligible forms are a plain 404. The
response schemas are the trimmed portal shapes, never the full internal reads."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser

from . import portal
from .schemas import FormSubmit, PortalFormRead, PortalGroup, PublicSubmitResult

router = APIRouter(prefix="/portal/forms", tags=["portal"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[PortalGroup])
async def list_portal_forms(session: Session, user: CurrentUser) -> list[PortalGroup]:
    """The form directory: enabled public + shared-with-me forms, grouped by project."""
    return await portal.list_portal_forms(session, actor=user)


@router.get("/{form_id}", response_model=PortalFormRead)
async def render_portal_form(
    form_id: uuid.UUID, session: Session, user: CurrentUser
) -> PortalFormRead:
    """Render payload for an eligible actor — field definitions inlined
    (a portal visitor may not read the registry). Ineligible → 404."""
    return await portal.render_portal_form(session, form_id, actor=user)


@router.post("/{form_id}/submit", response_model=PublicSubmitResult, status_code=201)
async def submit_portal_form(
    form_id: uuid.UUID, data: FormSubmit, session: Session, user: CurrentUser
) -> PublicSubmitResult:
    """Eligible actors submit even without item.create — runs as the SYSTEM
    actor with the visitor as reporter (the share is the grant)."""
    return await portal.submit_portal_form(session, form_id, data, actor=user)
