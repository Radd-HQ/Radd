import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import deflect, semantic, service
from .schemas import DeflectResponse, SearchResponse, SearchResult, SemanticResponse
from .types import MAX_QUERY_CHARS

router = APIRouter(tags=["search"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/search", response_model=SearchResponse)
async def search(
    session: Session,
    user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    # Spec 86: unscoped — visibility is per-project RBAC inside the service.
    hits = await service.search(session, user, q, limit=limit)
    return SearchResponse(
        results=[
            SearchResult(
                item_id=hit.item_id,
                project_id=hit.project_id,
                key=hit.key,
                title=hit.title,
                snippet=hit.snippet,
            )
            for hit in hits
        ]
    )


@router.get("/search/deflect", response_model=DeflectResponse)
async def search_deflect(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID,
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
) -> DeflectResponse:
    """KB deflection for the new-issue flow (spec 66): wiki pages that may
    already answer it + previously RESOLVED items in the project. The docs
    half only renders for callers who also hold doc.read (no title leaks)."""
    project = await projects_service.get_project(session, project_id)
    permissions = await authz.require(session, user, Permission.ITEM_READ, project=project)
    q = q.strip()
    if not q:
        return DeflectResponse(docs=[], items=[])
    docs = (
        await deflect.deflect_docs(session, q)
        if Permission.DOC_READ in permissions
        else []
    )
    return DeflectResponse(docs=docs, items=await deflect.deflect_items(session, project, q))


@router.get("/search/semantic", response_model=SemanticResponse)
async def search_semantic(
    session: Session,
    user: CurrentUser,
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
) -> SemanticResponse:
    """Pure meaning-based retrieval over items + docs (spec 103, the palette's
    Ask mode). `enabled: false` — never an error — when semantic search is not
    configured; RBAC scoping matches /search (items) and doc.read (docs)."""
    await authz.require(session, user, Permission.ITEM_READ)
    return await semantic.semantic_search(session, user, q)
