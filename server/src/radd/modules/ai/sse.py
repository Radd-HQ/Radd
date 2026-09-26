"""SSE bodies for streamed AI answers: `data: {"t": …}` frames (JSON, so newlines
survive framing), then `event: done`. Headers are already sent when a body runs,
so a provider failure is an in-band `event: error` frame, never an exception."""

import json
from collections.abc import AsyncIterator, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from . import client
from .images import ImagePart, wire, with_images
from .types import AiDisabledError, AiUpstreamError


def sse_frame(data: dict, event: str | None = None) -> str:
    """One SSE frame (pure)."""
    frame = f"data: {json.dumps(data)}\n\n"
    return f"event: {event}\n{frame}" if event else frame


async def completion_frames(
    session: AsyncSession,
    system: str,
    user_prompt: str,
    pictures: Sequence[ImagePart] = (),
    *,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """One completion as SSE frames; with `pictures` the vision role answers."""
    role, text = with_images(user_prompt, pictures)
    try:
        async for chunk in client.stream(
            session, role, system, text, max_tokens=max_tokens, images=wire(pictures)
        ):
            yield sse_frame({"t": chunk})
    except (AiUpstreamError, AiDisabledError) as exc:
        yield sse_frame({"detail": str(exc)}, event="error")
        return
    yield sse_frame({}, event="done")


async def done_only_frames() -> AsyncIterator[str]:
    """The empty stream: headers, `done`, nothing else."""
    yield sse_frame({}, event="done")
