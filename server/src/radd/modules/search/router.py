import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.deps import Actor
from radd.modules.projects import service as projects_service

from . import deflect, semantic, service
from .schemas import (
    DeflectResponse,
    EntityHit,
    EntitySearchGroup,
    EntitySearchResponse,
    SearchResponse,
    SearchResult,
    SemanticResponse,
)
from .types import MAX_QUERY_CHARS
from .deflect import DOCS_MODULE as PAGES_MODULE

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/search", response_model=SearchResponse)
async def search(
    session: Session,
    user: Actor,
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


@router.get("/search/entities", response_model=EntitySearchResponse)
async def search_entities(
    session: Session,
    user: Actor,
    q: Annotated[str, Query(max_length=200)] = "",
    types: Annotated[str, Query(description="Comma-separated entity types; empty = all")] = "",
    exclude: Annotated[str, Query(description="Comma-separated entity types to leave out")] = "",
    mentionable: bool = False,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> EntitySearchResponse:
    """Every registered searchable type (RADD-1327), each answered by its OWNER
    and so filtered by the owner's read gate. Grouped per type, in palette
    order. `mentionable=true` is the editor's `#` picker: only types a mention
    can name. A type whose search raises is left out rather than failing the
    palette."""
    from radd.kernel import registries

    wanted = {t for t in types.split(",") if t}
    skipped = {t for t in exclude.split(",") if t}
    q = q.strip()
    groups: list[EntitySearchGroup] = []
    if not q:
        return EntitySearchResponse(groups=[])
    for spec in sorted(registries.searchables.values(), key=lambda s: (s.order, s.label)):
        if (wanted and spec.entity_type not in wanted) or spec.entity_type in skipped:
            continue
        if mentionable and not spec.mentionable:
            continue
        try:
            hits = await spec.search(session, user, q, limit)
        except Exception:  # noqa: BLE001 — one owner's failure must not blank the palette
            logger.exception("search: %s search failed", spec.entity_type)
            continue
        if hits:
            groups.append(
                EntitySearchGroup(
                    entity_type=spec.entity_type,
                    label=spec.label,
                    hits=[EntityHit(entity_type=spec.entity_type, **hit) for hit in hits],
                )
            )
    return EntitySearchResponse(groups=groups)


@router.get("/search/deflect", response_model=DeflectResponse)
async def search_deflect(
    session: Session,
    user: Actor,
    project_id: uuid.UUID,
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
) -> DeflectResponse:
    """KB deflection for the new-issue flow (spec 66): wiki pages that may
    already answer it + previously RESOLVED items in the project. The docs
    half only renders for callers who also hold page.read (no title leaks)."""
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, Permission.ITEM_READ, project=project)
    q = q.strip()
    if not q:
        return DeflectResponse(docs=[], items=[])
    # RADD-791: page.read is SPACE-scoped now, so "does this project's permission
    # set contain it" is no longer a question that means anything. Deflect into
    # the spaces this reader may actually open.
    docs = await deflect.deflect_docs(session, q, space_ids=await _readable_space_ids(session, user), actor=user)
    return DeflectResponse(
        docs=docs, items=await deflect.deflect_items(session, project, q, actor=user)
    )


async def _readable_space_ids(session, user) -> set[uuid.UUID]:
    """The reader's wiki spaces, or an empty set when the wiki is not mounted."""
    if PAGES_MODULE not in settings.modules:
        return set()
    from radd.modules.pages import access as pages_access

    return set(await pages_access.readable_spaces(session, user))


@router.get("/search/semantic", response_model=SemanticResponse)
async def search_semantic(
    session: Session,
    user: Actor,
    q: Annotated[str, Query(max_length=MAX_QUERY_CHARS)] = "",
) -> SemanticResponse:
    """Pure meaning-based retrieval over items + docs (spec 103, the palette's
    Ask mode). `enabled: false` — never an error — when semantic search is not
    configured; RBAC scoping matches /search (items) and page.read (docs)."""
    await authz.require_member(session, user)  # RADD-788; results are RBAC-scoped below
    return await semantic.semantic_search(session, user, q)
