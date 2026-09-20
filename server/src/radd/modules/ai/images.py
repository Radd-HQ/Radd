"""The pictures a summary may look at (RADD-1275).

A page or issue that carries screenshots, diagrams or photos was summarised
from its text alone: `prose()` turns an inline image into `[image] alt` (so a
base64 screenshot cannot eat the budget — RADD-1232) and attachments were
never sent at all. When the instance has a VISION role, the summary can see
the pictures too — a screenshot of a stack trace is often the whole point of
the page.

Rules, in the order they are applied:
  1. only when the vision role resolves — with no vision model the text-only
     path is byte-identical to before;
  2. only the entity's attachments whose media type the role accepts
     (`VISION_IMAGE_TYPES`), stored, at or under `ai_vision_max_image_bytes`,
     newest first, at most `ai_vision_max_images`;
  3. only the ones the READER may open (`acl.attachment_readable`, the spec-102
     chokepoint) — an image someone cannot download is not shown to a model on
     their behalf;
  4. downscaled to `ai_vision_image_width` where the type allows, so a 4 MB
     photo is a few hundred kilobytes of tokens.

Video and audio are out of scope: no role exists for them. Inline data-URI
images in the body stay out too (unbounded; RADD-1232 removed them on purpose).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.attachments import acl, thumbnails
from radd.modules.attachments import service as attachments_service
from radd.modules.attachments.types import AttachmentParentType, AttachmentState
from radd.modules.auth.models import User

from . import registry
from .types import VISION_IMAGE_TYPES, AiRole

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImagePart:
    """One picture bound for the model: bytes, their media type, and the name
    the prompt calls it by."""

    data: bytes
    media_type: str
    filename: str


class AttachmentLike(Protocol):
    """What the picker reads — the Attachment row's columns, nothing more, so
    the rule is unit-testable over plain objects."""

    content_type: str
    size_bytes: int
    state: str
    created_at: object


def _media_type(content_type: str) -> str:
    return content_type.lower().split(";")[0].strip()


def pick_images[T: AttachmentLike](
    rows: Sequence[T], *, max_images: int, max_bytes: int
) -> list[T]:
    """Pure: the rows a vision model may see, newest first, capped (rule 2)."""
    eligible = [
        row
        for row in rows
        if _media_type(row.content_type) in VISION_IMAGE_TYPES
        and row.size_bytes <= max_bytes
        and row.state == AttachmentState.STORED.value
    ]
    eligible.sort(key=lambda row: row.created_at, reverse=True)  # type: ignore[arg-type]
    return eligible[:max_images]


def images_note(parts: Sequence[ImagePart]) -> str:
    """The line that tells the model what it is looking at — by filename, so
    the summary can say "the screenshot `crash.png`" rather than "an image"."""
    if not parts:
        return ""
    names = ", ".join(part.filename for part in parts)
    return f"Images attached ({len(parts)}), in order: {names}. Refer to them by filename."


async def vision_available(session: AsyncSession) -> bool:
    return await registry.resolve_role(session, AiRole.VISION) is not None


async def entity_images(
    session: AsyncSession,
    actor: User,
    entity_type: str,
    entity_id: uuid.UUID,
) -> list[ImagePart]:
    """The pictures of one entity that THIS reader may show a vision model.

    Empty — without touching storage — when no vision role is assigned or the
    entity type carries no attachments. A picture that cannot be read or
    resized is skipped and logged, never fatal: the summary still runs.
    """
    if entity_type not in {member.value for member in AttachmentParentType}:
        return []
    if not await vision_available(session):
        return []
    rows = await attachments_service.list_for_entity(session, entity_type, entity_id)
    chosen = pick_images(
        rows,
        max_images=settings.ai_vision_max_images,
        max_bytes=settings.ai_vision_max_image_bytes,
    )
    parts: list[ImagePart] = []
    for attachment in chosen:
        if not await acl.attachment_readable(session, actor, attachment):
            continue
        try:
            data = await attachments_service.read_blob(
                session, attachment.storage_name, host_id=attachment.storage_host_id
            )
            media_type = _media_type(attachment.content_type)
            if thumbnails.can_resize(media_type):
                smaller = await thumbnails.resized(data, media_type, settings.ai_vision_image_width)
                if smaller is not None:
                    data, media_type = smaller
                    media_type = _media_type(media_type)
        except Exception:  # noqa: BLE001 — one unreadable picture must not sink the summary
            logger.warning(
                "ai.images: skipping attachment %s (%s) — could not read it",
                attachment.id,
                attachment.filename,
                exc_info=True,
            )
            continue
        parts.append(ImagePart(data=data, media_type=media_type, filename=attachment.filename))
    return parts
