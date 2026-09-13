"""Semantic candidate retrieval (spec 103) — the seam `search` consumes via a
deferred, feature-detected import (the deflect/DOCS_MODULE precedent, direction
reversed: search may not import ai's tables, so ai exposes candidate functions
over its own).

Every function degrades to empty rather than raising — the callers fuse with
FTS and must keep working verbatim when semantic is off, unconfigured, or the
provider is down.
"""

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from .. import client, features, registry
from ..types import AiDisabledError, AiFeature, AiRole, AiUpstreamError
from . import service as store

logger = logging.getLogger(__name__)


async def semantic_enabled(session: AsyncSession) -> bool:
    """Toggle + role + extension, in cheap-first order."""
    if not await store.vector_available(session):
        return False
    return await features.feature_enabled(session, AiFeature.SEMANTIC_SEARCH)


async def _query_vector(session: AsyncSession, q: str) -> tuple[list[float], str] | None:
    resolved = await registry.resolve_role(session, AiRole.EMBEDDINGS)
    if resolved is None:
        return None
    try:
        vectors = await client.embed(session, AiRole.EMBEDDINGS, [q])
    except (AiUpstreamError, AiDisabledError) as exc:
        logger.warning("semantic search: embed failed (%s)", exc.__class__.__name__)
        return None
    if not vectors or not vectors[0]:
        return None
    return vectors[0], resolved.model


async def item_candidates(
    session: AsyncSession,
    q: str,
    *,
    project_ids: Sequence[uuid.UUID],
    exclude_item_id: uuid.UUID | None = None,
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    """(item_id, cosine distance) nearest-first, RBAC pre-filtered in SQL."""
    embedded = await _query_vector(session, q)
    if embedded is None:
        return []
    vector, model = embedded
    return await store.nearest_items(
        session,
        vector,
        model=model,
        dim=len(vector),
        project_ids=list(project_ids),
        exclude_item_id=exclude_item_id,
        limit=limit,
    )


async def item_neighbors(
    session: AsyncSession,
    item_id: uuid.UUID,
    fallback_text: str,
    *,
    project_ids: Sequence[uuid.UUID],
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    """Nearest items to an EXISTING item (similar-issues): its stored vector
    when fresh, else embed the fallback text on the fly."""
    resolved = await registry.resolve_role(session, AiRole.EMBEDDINGS)
    if resolved is None:
        return []
    vector = await store.item_embedding(session, item_id, model=resolved.model)
    if vector is None:
        embedded = await _query_vector(session, fallback_text)
        if embedded is None:
            return []
        vector = embedded[0]
    return await store.nearest_items(
        session,
        vector,
        model=resolved.model,
        dim=len(vector),
        project_ids=list(project_ids),
        exclude_item_id=item_id,
        limit=limit,
    )


async def doc_candidates(
    session: AsyncSession, q: str, *, limit: int
) -> list[tuple[uuid.UUID, float]]:
    """Nearest pages for `q` — UNSCOPED: the caller constrains to the actor's
    readable spaces (RADD-1147 retired the embed-time public flag)."""
    embedded = await _query_vector(session, q)
    if embedded is None:
        return []
    vector, model = embedded
    return await store.nearest_docs(session, vector, model=model, dim=len(vector), limit=limit)
