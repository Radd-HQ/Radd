"""Editor AI endpoints (spec 103). Session-cookie auth (any authenticated user —
the document is client-supplied, so a caller can only "leak" text they already
hold); gated per-instance by the editor_actions feature toggle (404-dormant)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import commit_before_streaming, get_session
from radd.modules.auth.deps import CurrentUser

from . import editor, features, images
from .schemas import EditorActionRead, EditorStreamRequest
from .types import SSE_HEADERS, AiFeature

router = APIRouter(prefix="/ai/editor", tags=["ai editor"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/actions", response_model=list[EditorActionRead])
async def list_actions(session: Session, user: CurrentUser) -> list[EditorActionRead]:
    await features.require_feature(session, AiFeature.EDITOR_ACTIONS)
    return await editor.list_actions(session)


@router.post("/stream")
async def stream(data: EditorStreamRequest, session: Session, user: CurrentUser) -> StreamingResponse:
    """SSE: `data: {"t": ...}` text frames, then `event: done` — or an in-band
    `event: error` frame (headers are gone by the time upstream can fail).

    Gate + action resolution run BEFORE streaming starts so a dormant feature
    404s and an unknown action_id 404s as ordinary JSON errors.
    """
    await features.require_feature(session, AiFeature.EDITOR_ACTIONS)
    instruction = await editor.resolve_instruction(session, data)
    # RADD-1275: the pictures the READER may show a vision model, read here
    # with the actor — the body generator has no caller to check against.
    pictures = (
        await images.entity_images(
            session, user, data.images_of.entity_type, data.images_of.entity_id
        )
        if data.images_of
        else []
    )
    # RADD-845: end the request tx before the stream; the generator's own
    # provider-config read autobegins a short one, bounded by the engine's
    # idle-in-transaction timeout.
    await commit_before_streaming(session)
    return StreamingResponse(
        editor.stream_frames(session, data, instruction, pictures),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
