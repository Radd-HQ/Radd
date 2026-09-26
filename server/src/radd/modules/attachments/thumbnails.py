"""Serving an image at the width the document asked for (RADD-751).

Markdown has nowhere to put a size, so a resize is the URL convention `?w=640`;
honouring it here is what makes a resized image ship fewer bytes, not just look
smaller. Widths are BUCKETED (rounded up, so the browser never upscales) to
bound re-encodes and cache keys, and resizing only ever goes DOWN — a width at
or above the original serves the original bytes.
"""

from __future__ import annotations

import asyncio
import io
import logging

logger = logging.getLogger(__name__)

#: What a `?w=` is rounded up to. Coarse on purpose — see the module docstring.
WIDTH_BUCKETS: tuple[int, ...] = (160, 320, 480, 640, 800, 1024, 1280, 1600, 1920)

#: Formats worth re-encoding. Anything else (SVG, which is already small and is
#: vector; anything non-image) is served untouched.
RESIZABLE_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)

#: JPEG/WebP quality. 82 is the usual knee: visually indistinguishable from 95
#: at roughly half the bytes.
QUALITY = 82


def bucket_for(width: int | None) -> int | None:
    """The bucket a requested width rounds up to, or None to serve the original."""
    if not width or width <= 0:
        return None
    for bucket in WIDTH_BUCKETS:
        if width <= bucket:
            return bucket
    # Wider than the widest bucket: the original is what they want.
    return None


def can_resize(content_type: str) -> bool:
    return content_type.lower().split(";")[0].strip() in RESIZABLE_TYPES


async def resized(data: bytes, content_type: str, width: int) -> tuple[bytes, str] | None:
    """`(bytes, content_type)` at `width`, or None to serve the original — every
    failure (Pillow unable to read the file included) falls back to it."""
    if not can_resize(content_type):
        return None
    bucket = bucket_for(width)
    if bucket is None:
        return None
    try:
        return await asyncio.to_thread(_resize, data, content_type, bucket)
    except Exception:  # noqa: BLE001 — delivering the original always beats failing
        logger.warning("could not resize an image; serving the original", exc_info=True)
        return None


def _resize(data: bytes, content_type: str, width: int) -> tuple[bytes, str] | None:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        # Re-encoding an animated GIF loses the animation: worse than a big file.
        if getattr(image, "is_animated", False):
            return None
        if image.width <= width:
            return None
        height = max(1, round(image.height * width / image.width))
        # Not `thumbnail`, which would also cap the height: this is a WIDTH convention.
        resized_image = image.resize((width, height), Image.LANCZOS)

        fmt = (image.format or "PNG").upper()
        out = io.BytesIO()
        if fmt in {"JPEG", "MPO"}:
            resized_image.convert("RGB").save(out, "JPEG", quality=QUALITY, optimize=True)
            return out.getvalue(), "image/jpeg"
        if fmt == "WEBP":
            resized_image.save(out, "WEBP", quality=QUALITY, method=4)
            return out.getvalue(), "image/webp"
        # Everything else stays PNG: JPEG rings around text, i.e. screenshots.
        resized_image.save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png"
