"""Similar: semantic-first candidate retrieval with an FTS fallback + optional
LLM rerank, split out of `service.py` (RADD-902) along its own "similar
(semantic-first; degrades, never disappears)" marker.

`extract_json_object` travelled to `nlslq.py` instead of staying here even
though it sits physically inside the original "similar" section — its only
caller is `nl_to_slq`, never anything in this file (`similar_items` uses
`extract_json_array`, a different function). Private helpers move with their
consumer, not with the section they happened to be typed under.

`service.py` re-exports everything here — including `_semantic_pool` and
`search_service` — under its own name; `tests/test_ai.py` monkeypatches THIS
module directly (`similar._semantic_pool`, `similar.search_service`) since a
patch on the facade's re-exported attribute would not reach the code running
in this module's own globals.
"""

import json
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.items import service as items_service
from radd.modules.search import service as search_service
from radd.modules.search.service import SearchHit
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from . import client, features, prompts
from .prose import prose
from .editor import sse_frame
from .types import (
    FTS_MATCH_REASON,
    SIMILAR_CANDIDATE_POOL,
    SUMMARY_MAX_DESCRIPTION_CHARS,
    AiDisabledError,
    AiFeature,
    AiRole,
    AiUpstreamError,
    SimilarCandidate,
    SimilarResponse,
)


def fts_candidates(hits: Sequence[tuple[SearchHit, float]]) -> list[SimilarCandidate]:
    """FTS ranks -> 0..1 scores by dividing by the top rank (pure)."""
    top = max((rank for _, rank in hits), default=0.0)
    return [
        SimilarCandidate(
            item_key=hit.key,
            title=hit.title,
            score=round(rank / top, 3) if top > 0 else 0.0,
            reason=FTS_MATCH_REASON,
        )
        for hit, rank in hits
    ]


def extract_json_array(text: str) -> list | None:
    """First JSON array in an LLM reply, tolerant of prose/code fences (pure).

    Tries every '[' as a start offset until one parses; None when nothing does.
    """
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\[", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except ValueError:
            continue
        if isinstance(value, list):
            return value
    return None


def parse_stream_objects(buffer: str, offset: int) -> tuple[list[dict], int]:
    """Complete top-level JSON objects in `buffer[offset:]` plus the resume
    offset (pure). The similar-reasons stream feeds the GROWING reply through
    this and emits one SSE event per completed candidate object — an object
    split across chunks stays unconsumed until its closing brace arrives, and
    a brace inside an unterminated string keeps the whole object pending."""
    decoder = json.JSONDecoder()
    found: list[dict] = []
    cursor = offset
    while True:
        start = buffer.find("{", cursor)
        if start == -1:
            return found, len(buffer)  # nothing pending — resume at the end
        try:
            value, consumed = decoder.raw_decode(buffer[start:])
        except ValueError:
            return found, start  # incomplete — retry from this object next chunk
        if isinstance(value, dict):
            found.append(value)
        cursor = start + consumed


def clean_reason_entry(entry: dict, allowed: set[str], seen: set[str]) -> dict | None:
    """One streamed model entry -> the {key, score, reason} SSE payload, or
    None for unusable entries (pure; mirrors apply_rerank's tolerance: unknown
    or duplicate keys and non-numeric scores are dropped). Mutates `seen`."""
    key = entry.get("key") or entry.get("item_key")
    score = entry.get("score")
    if not isinstance(key, str) or key not in allowed or key in seen:
        return None
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    seen.add(key)
    reason = entry.get("reason")
    return {
        "key": key,
        "score": round(min(max(float(score), 0.0), 1.0), 3),
        "reason": reason if isinstance(reason, str) and reason else None,
    }


def apply_rerank(
    candidates: Sequence[SimilarCandidate], parsed: Sequence[Any]
) -> list[SimilarCandidate] | None:
    """Merge the LLM's [{key, score, reason}] onto the FTS candidates (pure).

    Unknown/duplicate keys and malformed entries are ignored; candidates the
    model omitted are filtered out (its filter pass); result ordered by score
    descending. None when nothing usable survives -> caller keeps FTS order.
    """
    by_key = {candidate.item_key: candidate for candidate in candidates}
    merged: list[SimilarCandidate] = []
    seen: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key") or entry.get("item_key")
        score = entry.get("score")
        if not isinstance(key, str) or key not in by_key or key in seen:
            continue
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            continue
        seen.add(key)
        reason = entry.get("reason")
        merged.append(
            by_key[key].model_copy(
                update={
                    "score": round(min(max(float(score), 0.0), 1.0), 3),
                    "reason": reason if isinstance(reason, str) and reason else by_key[key].reason,
                }
            )
        )
    if not merged:
        return None
    merged.sort(key=lambda candidate: candidate.score, reverse=True)
    return merged


SEMANTIC_MATCH_REASON = "semantic match"


async def _semantic_pool(
    session: AsyncSession,
    text_seed: str,
    actor: User,
    *,
    item_id: uuid.UUID | None = None,
    exclude_item_id: uuid.UUID | None = None,
) -> list[SimilarCandidate]:
    """Vector-NN candidates (spec 103), [] on any failure or when semantic
    search is off — the FTS pool always stands on its own. Seeded by an item's
    stored vector when `item_id` is given (its neighbors exclude it), else by
    embedding `text_seed` on the fly (read-mode AI menu on comments)."""
    try:
        from radd.modules.ai.embeddings import candidates as semantic
    except ImportError:
        return []
    try:
        if not await semantic.semantic_enabled(session):
            return []
        readable = await search_service.readable_project_ids(session, actor)
        if not readable:
            return []
        # RADD-817: the ANN prefilter is project-level; relation-scoped readers
        # get their pool narrowed at materialization (below), through the same
        # clause every list shares.
        from radd.modules.auth import authz as _authz
        from radd.modules.items.models import WorkItem as _WorkItem
        from radd.modules.items.service.visibility import relation_read_clause

        relation_clause = await relation_read_clause(
            session, actor, await _authz.readable_projects(session, actor)
        )
        if item_id is not None:
            neighbors = await semantic.item_neighbors(
                session,
                item_id,
                text_seed,
                project_ids=list(readable),
                limit=SIMILAR_CANDIDATE_POOL,
            )
        else:
            neighbors = await semantic.item_candidates(
                session,
                text_seed,
                project_ids=list(readable),
                exclude_item_id=exclude_item_id,
                limit=SIMILAR_CANDIDATE_POOL,
            )
        if relation_clause is not None and neighbors:
            from sqlalchemy import select as _select

            visible = set(
                (
                    await session.execute(
                        _select(_WorkItem.id).where(
                            _WorkItem.id.in_([nid for nid, _ in neighbors]), relation_clause
                        )
                    )
                ).scalars()
            )
            neighbors = [(nid, d) for nid, d in neighbors if nid in visible]
        if not neighbors:
            return []
        rows = await search_service.rows_for_embedding(
            session, item_ids=[neighbor_id for neighbor_id, _ in neighbors]
        )
        titles = {row.item_id: (row.key, row.title) for row in rows}
        pool: list[SimilarCandidate] = []
        for neighbor_id, distance in neighbors:
            named = titles.get(neighbor_id)
            if named is None:
                continue
            pool.append(
                SimilarCandidate(
                    item_key=named[0],
                    title=named[1],
                    score=round(max(0.0, 1.0 - distance), 3),
                    reason=SEMANTIC_MATCH_REASON,
                )
            )
        return pool
    except Exception:  # noqa: BLE001 — similar must never 500 over the vector half
        return []


async def similar_items(
    session: AsyncSession, item_id: uuid.UUID, actor: User, *, limit: int
) -> SimilarResponse:
    """Candidate duplicates for an item: SEMANTIC-FIRST — the
    stored vector's neighbors ARE the pool when the embedding half is up; the
    OR-ed FTS pool runs only as the fallback (one shared common token was
    enough to surface an unrelated issue as a top "text match", and its
    top-rank-normalized score always read 100%). LLM-rescored when the rerank
    feature is enabled. Degrades pool by pool — FTS-only without pgvector,
    unreranked without a chat model."""
    read = await items_service.get_item(session, item_id, actor)  # enforces item.read
    ai_on = await features.feature_enabled(session, AiFeature.SIMILAR_RERANK)
    stream_on = bool(await settings_service.resolve(session, SettingKey.AI_STREAM_RESPONSES))
    text_seed = f"{read.title}\n{prose(read.description)}"  # RADD-1232
    snippets: dict[str, str] = {}
    candidates = await _semantic_pool(session, text_seed, actor, item_id=item_id)
    if not candidates:
        hits = await search_service.similar_to_text(
            session,
            text_seed,
            user=actor,
            exclude_item_id=item_id,
            limit=max(limit, SIMILAR_CANDIDATE_POOL) if ai_on else limit,
        )
        candidates = fts_candidates(hits)
        snippets = {hit.key: hit.snippet or "" for hit, _ in hits}
    if not ai_on or not candidates:
        return SimilarResponse(candidates=candidates[:limit], reranked=False)
    if stream_on:
        # Candidates go back NOW; the client follows up on the
        # /similar/reasons stream for scores + reasoning. reranked=False is
        # honest — this payload is the raw pool order.
        return SimilarResponse(candidates=candidates[:limit], reranked=False)

    reply = await client.complete(
        session,
        AiRole.CHAT,
        prompts.SIMILAR_SYSTEM,
        prompts.similar_user_prompt(
            key=read.key,
            title=read.title,
            description=prose(read.description)[:SUMMARY_MAX_DESCRIPTION_CHARS],
            # Semantic candidates carry no FTS headline — the model judges
            # those on title alone.
            candidates=[
                (candidate.item_key, candidate.title, snippets.get(candidate.item_key, ""))
                for candidate in candidates
            ],
        ),
    )
    parsed = extract_json_array(reply)
    if parsed is None:  # unparseable reply -> degrade to FTS order, flagged
        return SimilarResponse(candidates=candidates[:limit], reranked=False)
    if not parsed:  # an empty array is a real answer: nothing looks like a dup
        return SimilarResponse(candidates=[], reranked=True)
    reranked = apply_rerank(candidates, parsed)
    if reranked is None:
        return SimilarResponse(candidates=candidates[:limit], reranked=False)
    return SimilarResponse(candidates=reranked[:limit], reranked=True)


async def similar_to_seed(
    session: AsyncSession,
    text: str,
    actor: User,
    *,
    exclude_item_id: uuid.UUID | None,
    limit: int,
) -> SimilarResponse:
    """Candidate issues for a TEXT seed (read-mode AI menu on comments, the
    form assist panel): the same SEMANTIC-FIRST retrieval as `similar_items` —
    vector neighbors when the embedding half is up, the OR-ed FTS pool only as
    the fallback. Never LLM-reranked — the rerank prompt compares against a
    source issue, and a text seed has none."""
    candidates = await _semantic_pool(
        session, text, actor, exclude_item_id=exclude_item_id
    )
    if not candidates:
        hits = await search_service.similar_to_text(
            session, text, user=actor, exclude_item_id=exclude_item_id, limit=limit
        )
        candidates = fts_candidates(hits)
    return SimilarResponse(candidates=candidates[:limit], reranked=False)


async def similar_reasons_prompt(
    session: AsyncSession, item_id: uuid.UUID, actor: User, keys: Sequence[str]
) -> str | None:
    """Gate + rerank prompt for the reasons STREAM (run before the response
    starts, so a dormant feature 404s as ordinary JSON). The client sends the
    keys it is displaying — pools aren't perfectly deterministic between two
    calls — and titles are re-resolved under the caller's RBAC. None when no
    requested key survives: the stream is just `done`."""
    await features.require_feature(session, AiFeature.SIMILAR_RERANK)
    read = await items_service.get_item(session, item_id, actor)
    titled = await search_service.titles_for_keys(session, list(keys), user=actor)
    if not titled:
        return None
    return prompts.similar_user_prompt(
        key=read.key,
        title=read.title,
        description=prose(read.description)[:SUMMARY_MAX_DESCRIPTION_CHARS],
        candidates=[(key, title, "") for key, title in titled],
    )


async def similar_reason_frames(
    session: AsyncSession, user_prompt: str, keys: Sequence[str]
) -> AsyncIterator[str]:
    """SSE body: one `data: {"key", "score", "reason"}` frame per candidate as
    the model's JSON array streams in, then `event: done` — the panel hydrates
    reasons row by row instead of blocking the candidate list on the LLM."""
    allowed = set(keys)
    seen: set[str] = set()
    buffer = ""
    offset = 0
    try:
        async for chunk in client.stream(
            session, AiRole.CHAT, prompts.SIMILAR_SYSTEM, user_prompt
        ):
            buffer += chunk
            parsed, offset = parse_stream_objects(buffer, offset)
            for entry in parsed:
                payload = clean_reason_entry(entry, allowed, seen)
                if payload is not None:
                    yield sse_frame(payload)
    except (AiUpstreamError, AiDisabledError) as exc:
        yield sse_frame({"detail": str(exc)}, event="error")
        return
    yield sse_frame({}, event="done")


async def done_only_frames() -> AsyncIterator[str]:
    """The empty stream (no readable candidates): headers, `done`, nothing else."""
    yield sse_frame({}, event="done")
