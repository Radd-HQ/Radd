"""Public seam for mail contacts + the acknowledgment email (spec 62).

Other modules (forms' public submits, the csat sender's recipient resolution
[spec 65]; automations in spec 66) address external requesters exclusively
through these functions — the `mail_contacts` table stays private to this module.
"""

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd import smtp
from radd.config import settings

from .models import MailContact
from .types import ACK_BODY_TEMPLATE, ACK_SUBJECT_TEMPLATE

logger = logging.getLogger(__name__)


async def contact_for_item(session: AsyncSession, item_id: uuid.UUID) -> MailContact | None:
    return await session.get(MailContact, item_id)


async def upsert_contact(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    email: str,
    name: str = "",
    message_id: str | None = None,
) -> MailContact:
    """Create the item's contact, or refresh an existing one. One contact per
    item (v1): an existing row keeps its address — a threaded reply from a
    second sender only advances `last_message_id` (and fills a blank name)."""
    contact = await session.get(MailContact, item_id)
    if contact is None:
        contact = MailContact(
            item_id=item_id,
            email=email.lower(),
            name=name,
            last_message_id=message_id or None,
        )
        session.add(contact)
    else:
        if message_id:
            contact.last_message_id = message_id
        if name and not contact.name:
            contact.name = name
    await session.flush()
    return contact


async def send_ack(*, email: str, name: str, item_key: str, title: str, message_id: str | None = None) -> None:
    """Acknowledge a newly created item to its contact — subject `[KEY] title`
    (the key threads their replies back), In-Reply-To when we hold an inbound
    Message-ID. Silently skipped when SMTP is unconfigured or acks are off;
    a delivery failure is logged, never raised (an ack must not fail intake)."""
    if not settings.smtp_host or not settings.mail_send_ack:
        return
    headers = {"In-Reply-To": message_id, "References": message_id} if message_id else None
    try:
        await asyncio.to_thread(
            smtp.send_message,
            email,
            ACK_SUBJECT_TEMPLATE.format(key=item_key, title=title),
            ACK_BODY_TEMPLATE.format(key=item_key),
            to_name=name,
            headers=headers,
        )
    except Exception:
        logger.exception("mailintake: ack send to %s for %s failed", email, item_key)
