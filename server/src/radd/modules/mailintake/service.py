"""Public seam for mail contacts, the acknowledgment, and the item-mail transport.

Other modules (forms' public submits, the csat sender's recipient resolution
[spec 65]; automations in spec 66) address external requesters exclusively
through these functions — the `mail_contacts` table stays private to this module.

`send_item_mail` / `outbound_configured` are re-exported from `transport.py`
(RADD-968): they are the seam NOTIFY calls to mail a user about an issue, and a
caller looks for a module's public functions here, not in a file named after the
implementation. Since RADD-970 the ack goes out through it too, so there is no
mail leaving this module by any other route.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.config import settings

from .models import MailContact
from .transport import outbound_configured, send_item_mail
from .types import ACK_SUBJECT_TEMPLATE

__all__ = [
    "contact_for_item",
    "outbound_configured",
    "send_ack",
    "send_item_mail",
    "upsert_contact",
]


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


async def send_ack(
    session: AsyncSession | None = None,
    *,
    item_id: uuid.UUID,
    email: str,
    name: str,
    item_key: str,
    title: str,
) -> None:
    """Acknowledge a newly created item to its contact, through the ONE transport
    (RADD-970).

    It used to dial `radd.smtp` directly off the environment, hand-building its
    In-Reply-To from the id the caller carried. Three things follow from routing
    it through `send_item_mail` instead:

    * it sends from the **default `mail_senders` row** (env relay as the
      fallback, exactly as before), so an admin who configured a sender in
      Settings → Email and set no `RADD_SMTP_*` finally gets acks;
    * the ack's OWN outbound Message-ID is recorded against the item, so when
      the requester replies to the receipt — the message their client is most
      likely to reply to, since it is the only one Radd sent them — it threads
      on a header instead of falling back to the subject key;
    * a failure is emitted as `mail.failed`, not only logged (RADD-960).

    In-Reply-To now comes from the message store rather than a parameter. That
    is not a shortcut: intake records the inbound id inside the transaction it
    then commits, and BOTH callers ack post-commit, so the store already holds
    the message being answered. One source for the thread beats a copy passed by
    hand — the copy is what goes stale.

    Subject stays `[KEY] title` verbatim (`pin_subject`), because the bracketed
    key is the threading fallback and the requester's own subject carries none.
    Still gated on `mail_send_ack`, still never raises: `send_item_mail` returns
    None for "nowhere to send from", which is the `outbound_configured` question
    asked at the only moment it can be answered without a second round trip.

    `session` is optional and forwarded: production acks post-commit and passes
    nothing, while a caller inside a transaction (a test) hands over its own.
    """
    if not settings.mail_send_ack:
        return
    rendered = mailrender.acknowledgement(
        mailrender.ItemMail(key=item_key, title=title, base_url=settings.app_base_url)
    )
    await send_item_mail(
        session,
        item_id=item_id,
        to_address=email,
        to_name=name,
        subject=ACK_SUBJECT_TEMPLATE.format(key=item_key, title=title),
        text=rendered.text,
        html=rendered.html,
        pin_subject=True,
    )

