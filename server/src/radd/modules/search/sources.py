"""The sources search consults through kernel sockets (RADD-1384).

Search is the MECHANISM — item full-text, RRF fusion, the time budget, the
full-text-only floor, the response shapes. Two things it shows are somebody
else's: documents (`pages` provides SEARCH_DOCUMENTS) and meaning-ranked
candidates (`ai` provides SEMANTIC_CANDIDATES). It reaches both through the
sockets, never an import, because `sockets.providers` answers only for plugins
loaded NOW: a plugin disabled at runtime stops contributing in the same breath,
where the old `settings.modules` probe read the BOOT config and kept serving a
disabled wiki's pages.

`DocumentHit` is the shape a document provider answers with — defined here, by
the consumer, and imported by the provider (pages → search, the right way).
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import sockets
from radd.kernel.sockets import SearchDocumentSource, SemanticCandidateSource, Socket

logger = logging.getLogger(__name__)

#: One provider's ranking: (id, cosine distance), nearest first.
Ranking = list[tuple[uuid.UUID, float]]


@dataclass(frozen=True)
class DocumentHit:
    """A document a reader may open. The container (`space_*`) rides along
    because both endpoints that show documents name it."""

    id: uuid.UUID
    space_id: uuid.UUID
    title: str
    space_name: str = ""
    snippet: str | None = None


def document_sources() -> list[SearchDocumentSource]:
    """Every document provider loaded now — none means issues alone."""
    return list(sockets.providers(Socket.SEARCH_DOCUMENTS).values())


async def semantic_sources(session: AsyncSession) -> list[SemanticCandidateSource]:
    """The semantic providers able to answer now. A provider whose check
    raises is skipped (logged): meaning is an enhancement, never a gate."""
    live: list[SemanticCandidateSource] = []
    for name, provider in sockets.providers(Socket.SEMANTIC_CANDIDATES).items():
        try:
            if await provider.enabled(session):
                live.append(provider)
        except Exception as exc:  # noqa: BLE001 — full-text only beats a 500
            logger.warning("semantic source %s skipped: %s", name, exc.__class__.__name__)
    return live


async def semantic_rankings(
    session: AsyncSession,
    live: Sequence[SemanticCandidateSource],
    entity_type: str,
    q: str,
    *,
    limit: int,
    project_ids: Sequence[uuid.UUID] | None = None,
    budget: float | None = None,
) -> list[Ranking]:
    """Each live provider's non-empty ranking for `entity_type`. `budget`
    (seconds) bounds each call — the hybrid `/search` passes one. ANY failure,
    a timeout included, drops that provider's ranking and nothing else."""
    rankings: list[Ranking] = []
    for provider in live:
        call = provider.candidates(
            session, entity_type, q, limit=limit, project_ids=project_ids
        )
        try:
            ranked = await (asyncio.wait_for(call, timeout=budget) if budget else call)
        except Exception as exc:  # noqa: BLE001 — full-text only beats a 500
            logger.warning("semantic candidates skipped: %s", exc.__class__.__name__)
            continue
        if ranked:
            rankings.append(list(ranked))
    return rankings


def ids_of(rankings: Sequence[Ranking]) -> list[list[uuid.UUID]]:
    """Rankings as bare id lists — what RRF fuses."""
    return [[entity_id for entity_id, _ in ranking] for ranking in rankings]


def nearest(rankings: Sequence[Ranking]) -> Ranking:
    """One nearest-first ranking over every provider's (the closest distance
    wins a tie) — for Ask mode, which shows the distance as a score."""
    best: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for entity_id, distance in ranking:
            if entity_id not in best or distance < best[entity_id]:
                best[entity_id] = distance
    return sorted(best.items(), key=lambda pair: pair[1])
