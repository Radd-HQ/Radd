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
from .schemas import (
    FormSubmit,
    PortalFormRead,
    PortalGroup,
    PortalRequestRead,
    PublicSubmitResult,
)

router = APIRouter(prefix="/portal/forms", tags=["portal"])
#: A SECOND router, and the prefix is why (RADD-785). "my requests" is not a
#: form, and hanging it off the forms router would make it `/portal/forms/
#: requests` — a literal segment declared after `/{form_id}`, which Starlette
#: matches first and answers with a 422 about parsing "requests" as a UUID
#: (RADD-761). A sibling prefix says what the resource is and cannot be
#: shadowed.
requests_router = APIRouter(prefix="/portal/requests", tags=["portal"])

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


@requests_router.get("", response_model=list[PortalRequestRead])
async def my_requests(session: Session, user: CurrentUser) -> list[PortalRequestRead]:
    """The requests this person filed (RADD-785).

    Any signed-in user, because the answer is already scoped to them — the query
    filters on `reporter_id`. Someone who has filed nothing gets an empty list,
    which is the correct answer rather than a refusal.
    """
    return await portal.list_my_requests(session, actor=user)
