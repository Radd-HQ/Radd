"""Deliberate export to external mail, independent of an agent's read access.

An agent being able to view zoned storage is NOT permission to copy it outside
that network. Hosts must opt in, and attachment grants always exclude a file.
The caller supplies only references from a public reply on this same issue.
"""
import asyncio
import io
import logging
import uuid
import warnings

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.mailtypes import MailAttachment
from radd.modules.access import service as access

from .clients import client_for
from .models import Attachment, StorageHost
from .types import AttachmentParentType, AttachmentState

logger = logging.getLogger(__name__)
MAX_IMAGES = 10
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
READ_TIMEOUT_SECONDS = 10
# SVG and arbitrary image/* declarations are deliberately insufficient.
IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}


def _verified_type(data: bytes) -> str | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                content_type = IMAGE_TYPES.get(image.format)
                if not content_type:
                    return None
                image.verify()
                return content_type
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        return None


async def images_for_email(
    session: AsyncSession, item_id: uuid.UUID, attachment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, MailAttachment]:
    """Fail closed before reading bytes; never mint a URL or use a default host.

Query fresh rows for each delivery, so a move or revoked host permission since
reply planning takes effect. Partial/unavailable exports must not drop the text.
"""
    ids = list(dict.fromkeys(attachment_ids))[:MAX_IMAGES]
    if not ids:
        return {}
    result = await session.execute(
        select(Attachment, StorageHost)
        .join(StorageHost, StorageHost.id == Attachment.storage_host_id)
        .where(
            Attachment.id.in_(ids),
            Attachment.entity_type == AttachmentParentType.ITEM.value,
            Attachment.entity_id == item_id,
            Attachment.state == AttachmentState.STORED.value,
            Attachment.content_type.in_(IMAGE_TYPES.values()),
            Attachment.size_bytes > 0,
            Attachment.size_bytes <= MAX_IMAGE_BYTES,
            StorageHost.email_images_allowed.is_(True),
        ).execution_options(populate_existing=True)
    )
    rows = {attachment.id: (attachment, host) for attachment, host in result.all()}
    grants = await access.grants_for_resources(session, "attachment", list(rows))
    exported: dict[uuid.UUID, MailAttachment] = {}
    total = 0
    for attachment_id in ids:
        if attachment_id not in rows or grants.get(str(attachment_id)):
            continue
        attachment, host = rows[attachment_id]
        if total + attachment.size_bytes > MAX_TOTAL_BYTES:
            continue
        try:
            client = client_for(host)
            stat = await asyncio.wait_for(client.stat(attachment.storage_name), READ_TIMEOUT_SECONDS)
            if not 0 < stat.size_bytes <= min(MAX_IMAGE_BYTES, MAX_TOTAL_BYTES - total):
                continue
            data = await asyncio.wait_for(client.read(attachment.storage_name), READ_TIMEOUT_SECONDS)
            if not 0 < len(data) <= min(MAX_IMAGE_BYTES, MAX_TOTAL_BYTES - total):
                continue
            content_type = await asyncio.to_thread(_verified_type, data)
            if content_type != attachment.content_type:
                continue
        except Exception:
            # No storage credentials, URLs or file names in the email or logs.
            logger.warning("mail image unavailable: attachment %s", attachment_id)
            continue
        filename = attachment.filename.replace("\\", "/").rsplit("/", 1)[-1]
        filename = "".join(c for c in filename if c.isprintable()).strip() or "image"
        exported[attachment_id] = MailAttachment(filename, content_type, data)
        total += len(data)
    return exported
