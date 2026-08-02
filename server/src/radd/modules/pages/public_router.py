"""Unauthenticated router for the public knowledge base (spec 74). The forms
public-router idiom: deliberately its own APIRouter, nothing here takes
CurrentUser — a space's `public` flag is the credential (unknown and non-public
alike → 404), and the response schemas are the trimmed public shapes, never the
full internal reads. No versions/history/links exposure."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session

from . import public
from .schemas import PageSearchResponse, PublicPageNode, PublicPageRead, PublicPageSpace
from .types import MAX_QUERY_CHARS

router = APIRouter(prefix="/public/pages", tags=["public-pages"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/spaces", response_model=list[PublicPageSpace])
async def list_spaces(session: Session) -> list[PublicPageSpace]:
    """Every public space's card — the /kb index."""
    return await public.list_public_spaces(session)


@router.get("/spaces/{space_id}/tree", response_model=list[PublicPageNode])
async def space_tree(space_id: uuid.UUID, session: Session) -> list[PublicPageNode]:
    """The non-archived page tree — 404 for unknown/non-public spaces."""
    return await public.public_tree(session, space_id)


@router.get("/pages/{page_id}", response_model=PublicPageRead)
async def get_page(page_id: uuid.UUID, session: Session) -> PublicPageRead:
    """One page's markdown body + breadcrumb (rendered client-side) — 404
    unless its space is public; archived → 404."""
    return await public.public_page(session, page_id)


@router.get("/search", response_model=PageSearchResponse)
async def search_public_kb(
    session: Session,
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
    space_id: uuid.UUID | None = None,
) -> PageSearchResponse:
    """Live FTS over PUBLIC spaces only (shared tsvector expression)."""
    return PageSearchResponse(results=await public.search_public(session, q, space_id=space_id))
