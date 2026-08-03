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
    """The requests this person may follow (RADD-785 → RADD-796/798).

    Any signed-in user, because the answer is already scoped to them: the query
    filters on `reporter_id == me OR team_id IN my teams`. Someone with no
    requests gets an empty list, which is the correct answer rather than a
    refusal.
    """
    return await requests_service.list_my_requests(session, actor=user)


@requests_router.get("/{key}", response_model=PortalRequestDetail)
async def get_request(key: str, session: Session, user: CurrentUser) -> PortalRequestDetail:
    """One request, opened (RADD-796).

    404 — never 403 — when the actor is neither the reporter nor in the request's
    team. A refusal would confirm the key names a real issue, which is the thing
    someone guessing keys is trying to learn.
    """
    return await requests_service.get_request(session, user, key)


@requests_router.post("/{key}/comments", response_model=PortalRequestComment, status_code=201)
async def reply_to_request(
    key: str, data: PortalRequestReply, session: Session, user: CurrentUser
) -> PortalRequestComment:
    """Answer a question asked of you. Forced PUBLIC at the service seam — the
    schema has no visibility field, so this cannot reach the internal thread."""
    return await requests_service.add_request_comment(session, user, key, data.body)
