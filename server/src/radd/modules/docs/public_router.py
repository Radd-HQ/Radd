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
from .schemas import DocSearchResponse, PublicKbPageNode, PublicKbPageRead, PublicKbSpace
from .types import MAX_QUERY_CHARS

router = APIRouter(prefix="/public/kb", tags=["public-kb"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/spaces", response_model=list[PublicKbSpace])
async def list_spaces(session: Session) -> list[PublicKbSpace]:
    """Every public space's card — the /kb index."""
    return await public.list_public_spaces(session)


@router.get("/spaces/{space_id}/tree", response_model=list[PublicKbPageNode])
async def space_tree(space_id: uuid.UUID, session: Session) -> list[PublicKbPageNode]:
    """The non-archived page tree — 404 for unknown/non-public spaces."""
    return await public.public_tree(session, space_id)


@router.get("/pages/{page_id}", response_model=PublicKbPageRead)
async def get_page(page_id: uuid.UUID, session: Session) -> PublicKbPageRead:
    """One page's markdown body + breadcrumb (rendered client-side) — 404
    unless its space is public; archived → 404."""
    return await public.public_page(session, page_id)


@router.get("/search", response_model=DocSearchResponse)
async def search_public_kb(
    session: Session,
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
    space_id: uuid.UUID | None = None,
) -> DocSearchResponse:
    """Live FTS over PUBLIC spaces only (shared tsvector expression)."""
    return DocSearchResponse(results=await public.search_public(session, q, space_id=space_id))
