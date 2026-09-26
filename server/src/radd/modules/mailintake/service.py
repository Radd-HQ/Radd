"""Public seam for mail contacts and the item-mail transport. Other modules
address external requesters only through these functions (`mail_contacts` stays
private); `send_item_mail`/`send_plain_mail`/`outbound_configured`/`mail_health`
are re-exported from `transport.py` — there is no other route out (RADD-983)."""

import re
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.notify.service import mailable_user
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from .models import MailContact
from .transport import (
    MailFailure,
    MailHealth,
    mail_health,
    outbound_configured,
    send_item_mail,
    send_plain_mail,
)
from .types import ACK_SUBJECT_TEMPLATE, SentMailKind

if TYPE_CHECKING:
    from .intake import AckPlan

__all__ = [
    "MailFailure",
    "MailHealth",
    "contact_for_item",
    "contacts_for_item",
    "mail_health",
    "mailable_user",
    "outbound_configured",
    "send_ack",
    "send_item_mail",
    "send_plain_mail",
    "SentMailKind",
    "upsert_contact",
]


#: Primary first, then oldest, then alphabetical — shared by both reads. The address,
#: not the id, breaks ties: `created_at` is TRANSACTION time, so every contact from
#: ONE message ties, and a uuid4 tiebreak would shuffle the rail on every read.
_CONTACT_ORDER = (MailContact.is_primary.desc(), MailContact.created_at, MailContact.email)


async def contact_for_item(session: AsyncSession, item_id: uuid.UUID) -> MailContact | None:
    """The item's PRIMARY contact or None — FILTERED on `is_primary`, so an item
    whose only external addresses were copied in falls back to its reporter."""
    return await session.scalar(
        select(MailContact)
        .where(MailContact.item_id == item_id, MailContact.is_primary.is_(True))
        .order_by(*_CONTACT_ORDER)
    )


async def contacts_for_item(
    session: AsyncSession, item_id: uuid.UUID
) -> list[MailContact]:
    """Everyone external on this item's mail thread, primary first (RADD-980) —
    what an outbound reply fans out over."""
    rows = await session.execute(
        select(MailContact).where(MailContact.item_id == item_id).order_by(*_CONTACT_ORDER)
    )
    return list(rows.scalars())


async def upsert_contact(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    email: str,
    name: str = "",
    message_id: str | None = None,
    copied_in: bool = False,
) -> MailContact:
    """Record one external address on an item, or refresh it; keyed on
    `(item_id, email)` (RADD-980). The first person who WROTE becomes primary;
    `copied_in` can only withhold the badge, never award it, and nothing demotes
    a primary — so a CC can never silently become the requester.
    """
    address = email.strip().lower()
    existing = await contacts_for_item(session, item_id)
    contact = next((row for row in existing if row.email == address), None)
    if contact is None:
        contact = MailContact(
            item_id=item_id,
            email=address,
            name=name,
            last_message_id=message_id or None,
            is_primary=not copied_in and not any(row.is_primary for row in existing),
        )
        session.add(contact)
    else:
        if message_id:
            contact.last_message_id = message_id
        if name and not contact.name:
            contact.name = name
    await session.flush()
    return contact


#: The `{{token}}` idiom of `canned.render`: an unknown or empty token stays VERBATIM.
_ACK_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _render_ack_body(template: str, ctx: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = ctx.get(match.group(1))
        return match.group(0) if not value else value

    return _ACK_TOKEN_RE.sub(replace, template)


async def send_ack(ack: "AckPlan", session: AsyncSession | None = None) -> str | None:
    """Send the receipt for a new email ticket when `mail_send_ack` is on
    (RADD-1368); returns the Message-ID or None. Called POST-COMMIT so the inbound
    id is in the store for In-Reply-To (`session` is for a test's transaction).
    The subject `[KEY] title` is pinned (the key threads replies); a blank
    `mail_ack_body` sends the default wording. Never raises.
    """
    async def read(own: AsyncSession) -> tuple[bool, str]:
        enabled = await settings_service.resolve(own, SettingKey.MAIL_SEND_ACK, project_id=ack.project_id)
        body = await settings_service.resolve(own, SettingKey.MAIL_ACK_BODY)
        return bool(enabled), str(body or "")

    if session is not None:
        enabled, template = await read(session)
    else:
        async with SessionLocal() as own:
            enabled, template = await read(own)
    if not enabled:
        return None
    if not template.strip():
        template = settings.mail_ack_body
    link = mailrender.issue_url(settings.app_base_url, ack.item_key)
    body = _render_ack_body(
        template, {"key": ack.item_key, "title": ack.title, "link": link, "requester_name": ack.name}
    )
    rendered = mailrender.contact_notice(
        mailrender.ItemMail(key=ack.item_key, title=ack.title, base_url=settings.app_base_url), body=body
    )
    return await send_item_mail(
        session,
        item_id=ack.item_id,
        to_address=ack.email,
        to_name=ack.name,
        subject=ACK_SUBJECT_TEMPLATE.format(key=ack.item_key, title=ack.title),
        text=rendered.text,
        html=rendered.html,
        pin_subject=True,
        kind=SentMailKind.RECEIPT,
    )
