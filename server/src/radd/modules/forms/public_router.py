"""Unauthenticated router for the public form path (spec 62). Deliberately its
own APIRouter: nothing here takes CurrentUser — the token IS the credential
(404 unknown, 409 disabled/not-public), and the response schemas are the
trimmed public shapes, never the full internal reads."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session

from . import public
from .schemas import (
    PublicDeflectResponse,
    PublicFormRead,
    PublicFormSubmit,
    PublicSubmitResult,
)

router = APIRouter(prefix="/public/forms", tags=["public-forms"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{token}", response_model=PublicFormRead)
async def render_public_form(token: str, session: Session) -> PublicFormRead:
    """Render payload for the tokened no-login submit page — field definitions
    inlined (the registry isn't reachable without a login)."""
    return await public.render_public_form(session, token)


@router.get("/{token}/deflect", response_model=PublicDeflectResponse)
async def deflect_public_form(
    token: str, session: Session, q: str = ""
) -> PublicDeflectResponse:
    """KB deflection for the anonymous visitor (spec 74): top public-KB pages
    for the half-typed title. Token-gated like the form; items never searched."""
    return await public.deflect_public_form(session, token, q)


@router.post("/{token}", response_model=PublicSubmitResult, status_code=201)
async def submit_public_form(
    token: str, data: PublicFormSubmit, session: Session
) -> PublicSubmitResult:
    """Anonymous submit: runs as the SYSTEM actor through the ordinary form
    path; the email becomes the reporter (registered) or the mail contact."""
    return await public.submit_public_form(session, token, data)
