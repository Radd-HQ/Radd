"""Serving an image at the width the document asked for (RADD-751).

Markdown cannot express an image size — `![alt](url)` has nowhere to put one —
so a resized image is written as a URL convention, `?w=640`. The body stays pure
markdown, which is what keeps FTS, the embedder, the export, MCP and the public
surface reading the same thing they always did.

The convention is also the only one of the three options considered that fixes
the BANDWIDTH problem rather than only the layout one: a 4 MB screenshot shown
at 600px currently ships 4 MB to every reader. Honouring the width here is what
makes "a resized image transfers fewer bytes" true instead of aspirational.

Two decisions worth stating:

- **Widths are BUCKETED.** An arbitrary width means a fresh decode-and-encode
  for every pixel someone drags through, and a cache key per pixel. Nine buckets
  cover the useful range; a request rounds UP so the image is never upscaled by
  the browser.
- **Only ever DOWN.** A width at or above the original returns the original
  bytes untouched — asking for a bigger image cannot make one, and pretending
  otherwise would ship more bytes than the original for a worse picture.
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
    """`(bytes, content_type)` at `width`, or None to serve the original.

    None rather than an exception for every "no" — a picture that cannot be
    resized must still be DELIVERED, so every failure here falls back to the
    original bytes. That includes Pillow being unable to read the file, which is
    a thing users will do.
    """
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
        # An animated GIF loses its animation on re-encode, which is a worse
        # outcome than a large file. Leave it alone.
        if getattr(image, "is_animated", False):
            return None
        if image.width <= width:
            return None
        height = max(1, round(image.height * width / image.width))
        # `thumbnail` would also cap the height; this is a WIDTH convention, so
        # a tall screenshot keeps its aspect ratio and gets as tall as it needs.
        resized_image = image.resize((width, height), Image.LANCZOS)

        fmt = (image.format or "PNG").upper()
        out = io.BytesIO()
        if fmt in {"JPEG", "MPO"}:
            resized_image.convert("RGB").save(out, "JPEG", quality=QUALITY, optimize=True)
            return out.getvalue(), "image/jpeg"
        if fmt == "WEBP":
            resized_image.save(out, "WEBP", quality=QUALITY, method=4)
            return out.getvalue(), "image/webp"
        # PNG and everything else stay PNG: a screenshot re-encoded as JPEG
        # gains ringing around text, which is most of what gets pasted here.
        resized_image.save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png"
