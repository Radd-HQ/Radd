"""Requester-portal router (spec 73): any signed-in user; eligibility per form is
the only gate (portal.py), ineligible = 404; responses are the trimmed shapes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser

from . import portal, requests as requests_service
from .schemas import (
    FormSubmit,
    PortalFormRead,
    PortalGroup,
    PortalRequestComment,
    PortalRequestDetail,
    PortalRequestRead,
    PortalRequestReply,
    PublicSubmitResult,
)

router = APIRouter(prefix="/portal/forms", tags=["portal"])
#: A sibling prefix, not `/portal/forms/requests`: a literal after `/{form_id}` is
#: shadowed (RADD-761).
requests_router = APIRouter(prefix="/portal/requests", tags=["portal"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[PortalGroup])
async def list_portal_forms(session: Session, user: CurrentUser) -> list[PortalGroup]:
    """The form directory: enabled public + shared-with-me forms, grouped by project."""
    return await portal.list_portal_forms(session, actor=user)


@router.get("/staging-area", response_model=dict[str, uuid.UUID])
async def staging_area(user: CurrentUser) -> dict[str, uuid.UUID]:
    """Where to stage a submission's files (RADD-800) — derived from the caller,
    never accepted. Declared above `/{form_id}` for the same route-order reason."""
    from . import staging

    return {"entity_id": staging.staging_id_for(user)}


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
    """Requests this person may follow — filtered to them, so never a refusal."""
    return await requests_service.list_my_requests(session, actor=user)


@requests_router.get("/{key}", response_model=PortalRequestDetail)
async def get_request(key: str, session: Session, user: CurrentUser) -> PortalRequestDetail:
    """One request (RADD-796); 404, never 403 — a refusal would confirm the key."""
    return await requests_service.get_request(session, user, key)


@requests_router.post("/{key}/comments", response_model=PortalRequestComment, status_code=201)
async def reply_to_request(
    key: str, data: PortalRequestReply, session: Session, user: CurrentUser
) -> PortalRequestComment:
    """Answer a question asked of you. Forced PUBLIC at the service seam — the
    schema has no visibility field, so this cannot reach the internal thread."""
    return await requests_service.add_request_comment(session, user, key, data.body)
