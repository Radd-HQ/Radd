"""Unauthenticated router for the public rating page (spec 65, the spec-62
public-forms idiom): its own APIRouter, nothing takes CurrentUser — the survey
token IS the credential (404 unknown), and the responses are the trimmed public
shapes. The page POSTs the rating; the emailed links only preselect a star, so
a mail scanner prefetching them can never record one."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session

from . import service
from .schemas import PublicCsatRead, PublicCsatSubmit

router = APIRouter(prefix="/public/csat", tags=["public-csat"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{token}", response_model=PublicCsatRead)
async def render_public_survey(token: str, session: Session) -> PublicCsatRead:
    """Render payload for the tokened rating page — shows the current answer
    when the requester already responded (re-submits are allowed, latest wins)."""
    return await service.public_survey(session, token)


@router.post("/{token}", response_model=PublicCsatRead)
async def submit_public_survey(
    token: str, data: PublicCsatSubmit, session: Session
) -> PublicCsatRead:
    """Record the rating (+ optional comment). Latest submit wins;
    `responded_at` is stamped on the first. Emits csat.responded."""
    return await service.record_response(session, token, data)
