"""Normalise, store, replace and serve profile pictures (RADD-1295)."""

import asyncio
import io
import logging

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.attachments import service as blobs
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User

logger = logging.getLogger(__name__)

AVATAR_PIXELS = 256
AVATAR_CONTENT_TYPE = "image/webp"
ACCEPTED_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
# A decompression bomb is a small file that decodes to gigapixels.
MAX_SOURCE_PIXELS = 40_000_000


def normalise(data: bytes) -> bytes:
    """Any accepted image -> a 256px square WebP: EXIF-rotated, centre-cropped,
    first frame only. Raises ValueError for anything that is not an image."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            if width * height > MAX_SOURCE_PIXELS:
                raise ValueError("that image is too large")
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.seek(0)
            frame = ImageOps.exif_transpose(image).convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("that file is not an image Radd can read") from exc
    square = ImageOps.fit(frame, (AVATAR_PIXELS, AVATAR_PIXELS), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    square.save(out, format="WEBP", quality=85, method=4)
    return out.getvalue()


async def upload(session: AsyncSession, user: User, file: UploadFile) -> User:
    if (file.content_type or "").lower() not in ACCEPTED_TYPES:
        raise HTTPException(415, "use a PNG, JPEG, WebP or GIF image")
    data = await file.read(settings.avatar_max_upload_bytes + 1)
    if len(data) > settings.avatar_max_upload_bytes:
        raise HTTPException(413, "that image is too large")
    try:
        picture = await asyncio.to_thread(normalise, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    stored = await blobs.save_blob(
        session,
        UploadFile(file=io.BytesIO(picture), filename="avatar.webp"),
        content_type=AVATAR_CONTENT_TYPE,
    )
    previous = await auth_service.set_avatar_blob(session, user, stored.storage_name, stored.host_id)
    await _discard(session, *previous)
    return user


async def remove(session: AsyncSession, user: User) -> User:
    if user.avatar_blob:
        previous = await auth_service.set_avatar_blob(session, user, None, None)
        await _discard(session, *previous)
    return user


async def picture(session: AsyncSession, user: User) -> bytes:
    if not user.avatar_blob:
        raise HTTPException(404, "no picture")
    return await blobs.read_blob(session, user.avatar_blob, host_id=user.avatar_blob_host_id)


async def _discard(session: AsyncSession, blob, host_id) -> None:
    """The replaced picture's bytes. Best-effort: a stale blob is litter, a
    failed profile save would be a bug."""
    if not blob:
        return
    try:
        await blobs.remove_blob(session, blob, host_id=host_id)
    except Exception:  # noqa: BLE001 — remove_blob already logged it
        logger.info("avatars: left blob %s behind", blob)
