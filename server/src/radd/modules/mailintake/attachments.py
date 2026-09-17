"""Only explicit, same-instance attachment references can become email parts.

No remote fetches, implicit issue-wide attachment collection or presigned URLs.
Both image and ordinary markdown links are supported; prose URLs are not an
instruction to export a file. The mail renderer escapes raw HTML as text.
"""
import re
import uuid
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.mailtypes import MailAttachment
from radd.modules.attachments.email_export import images_for_email

_LINK = re.compile(r'!?\[[^\]\n]*\]\(<?([^\s<>]+)>?(?:\s+"[^"\n]*")?\)')
_PATH = re.compile(r"/api/v1/attachments/([0-9a-fA-F-]{36})")


def _attachment_id(url: str) -> uuid.UUID | None:
    try:
        parsed = urlsplit(url)
        base = urlsplit(settings.app_base_url)
        if parsed.netloc and (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            return None
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            return None
        match = _PATH.fullmatch(parsed.path)
        return uuid.UUID(match[1]) if match else None
    except ValueError:
        return None


async def prepare(
    session: AsyncSession, item_id: uuid.UUID, body: str
) -> tuple[str, tuple[MailAttachment, ...]]:
    refs = [(match, _attachment_id(match[1])) for match in _LINK.finditer(body)]
    ids = [attachment_id for _, attachment_id in refs if attachment_id is not None]
    images = await images_for_email(session, item_id, ids)
    # Generic placeholders do not disclose a blocked file's name or storage.
    # Oversized/unavailable files remain behind the email's normal issue link.
    for match, attachment_id in reversed(refs):
        if attachment_id is None:
            continue
        replacement = "[Image attached]" if attachment_id in images else "[Attachment not included]"
        body = body[:match.start()] + replacement + body[match.end():]
    return body, tuple(images.values())
