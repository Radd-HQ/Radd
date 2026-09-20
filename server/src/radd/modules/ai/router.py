"""AI endpoints (spec 46). Ordinary RBAC on every path; summarize and NL->SLQ
return a clean 404 while no provider is configured, /items/{id}/similar and
/ai/status work regardless (similar degrades to FTS-only candidates)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import commit_before_streaming, get_session
from radd.modules.auth.deps import CurrentUser

from . import service
from .types import (
    SIMILAR_DEFAULT_LIMIT,
    SIMILAR_MAX_LIMIT,
    AiStatus,
    NlQueryRequest,
    NlQueryResponse,
    SimilarResponse,
    SSE_HEADERS,
    SimilarReasonsRequest,
    SimilarTextRequest,
    SummarizeResponse,
)

router = APIRouter(tags=["ai"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/ai/status", response_model=AiStatus)
async def ai_status(session: Session, user: CurrentUser) -> AiStatus:
    """Whether AI is configured (any authenticated member) — the frontend gates
    its AI affordances on `enabled` and per-feature on `features`."""
    return await service.status(session)


@router.post("/items/{item_id}/ai/summarize", response_model=SummarizeResponse)
async def summarize_item(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> SummarizeResponse:
    """Hand-off-style summary of the item (item.read): description + recent
    comments + history digest. Not stored — returned to the caller."""
    return await service.summarize_item(session, item_id, user)


@router.post("/items/{item_id}/ai/summarize/stream")
async def summarize_item_stream(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> StreamingResponse:
    """The same summary, streamed as SSE (the Stream-AI-responses instance
    setting). Gates + the digest build run before the stream starts, so a
    dormant feature or unreadable item fails as ordinary JSON."""
    user_prompt = await service.summarize_prompt(session, item_id, user)
    # RADD-1275: the pictures are read here, with the actor, before the
    # response starts — the body generator has no caller to check against.
    pictures = await service.summarize_images(session, item_id, user)
    await commit_before_streaming(session)  # RADD-845: no idle tx behind the SSE
    return StreamingResponse(
        service.summarize_stream_frames(session, user_prompt, pictures),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/items/{item_id}/ai/similar/reasons")
async def similar_reasons(
    item_id: uuid.UUID, data: SimilarReasonsRequest, session: Session, user: CurrentUser
) -> StreamingResponse:
    """LLM reasoning for a DISPLAYED candidate list, streamed as SSE — one
    `{key, score, reason}` frame per candidate. Split from /similar so the
    candidate rows render instantly and the chat-model round trip never blocks
    them (similar_rerank feature; 404-dormant)."""
    user_prompt = await service.similar_reasons_prompt(session, item_id, user, data.keys)
    frames = (
        service.similar_reason_frames(session, user_prompt, data.keys)
        if user_prompt is not None
        else service.done_only_frames()
    )
    await commit_before_streaming(session)  # RADD-845: no idle tx behind the SSE
    return StreamingResponse(frames, media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/items/{item_id}/similar", response_model=SimilarResponse)
async def similar_items(
    item_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=SIMILAR_MAX_LIMIT)] = SIMILAR_DEFAULT_LIMIT,
) -> SimilarResponse:
    """Candidate duplicates (item.read): FTS-ranked always; scored/filtered by
    the LLM when AI is enabled (`reranked` says which you got)."""
    return await service.similar_items(session, item_id, user, limit=limit)


@router.post("/ai/similar", response_model=SimilarResponse)
async def similar_to_text(
    data: SimilarTextRequest,
    session: Session,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=SIMILAR_MAX_LIMIT)] = SIMILAR_DEFAULT_LIMIT,
) -> SimilarResponse:
    """Candidate issues for a text seed (read-mode AI menu on a comment):
    fused FTS + vector pools scoped to the caller's readable projects, never
    reranked — there is no source issue to compare against."""
    return await service.similar_to_seed(
        session, data.text, user, exclude_item_id=data.exclude_item_id, limit=limit
    )


@router.post("/slq/nl", response_model=NlQueryResponse)
async def nl_to_slq(data: NlQueryRequest, session: Session, user: CurrentUser) -> NlQueryResponse:
    """Natural language -> SLQ (item.read). The query is compile-validated
    server-side; invalid -> one self-correcting retry, then 422 with the bad
    query + error."""
    return await service.nl_to_slq(
        session, question=data.question, actor=user, dialect=data.dialect
    )
