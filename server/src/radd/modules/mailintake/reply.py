"""WHO an outbound reply goes to, and WHAT it says (RADD-955, RADD-967, RADD-968).

Split out of `outbound.py`, which is the consumer that ships it: the cursor
idiom, the sender lookup and the delivery loop have nothing to do with the
recipient set, and both files were past the point where one screen showed either
concern whole.

**RADD-968 narrowed this to the requester conversation.** It used to mail
notify's watcher set as well, which was a SECOND fan-out beside the one that
decides the inbox — and the two disagreed: the inbox reaches watchers ∪
participant-team members and re-checks `item.read` per recipient and per row,
this reached watchers only and re-checked nothing. Users are now mailed by
notify, through the same permission-gated rows that produce their inbox; what is
left here is the one recipient notify can never have, because they have no
account: the external `mail_contact`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.modules.auth import service as auth

from . import service
from .types import REPLY_REASON_TEMPLATES, MailRecipientKind


@dataclass(frozen=True)
class Recipient:
    email: str
    name: str = ""
    #: Only one kind reaches this file now; the enum stays because the FOOTER is
    #: what it decides, and notify's watcher wording is the other half of it.
    kind: MailRecipientKind = MailRecipientKind.REQUESTER


@dataclass(frozen=True)
class OutboundReply:
    """One planned reply: the comment, and everyone it goes to.

    It carries the INGREDIENTS rather than a finished body, because the body is
    a function of the recipient (`render`). Threading is NOT among them: the
    transport seam resolves the chain and the subject from the message store at
    send time, so nothing here can go stale between planning and delivery.
    """

    item_id: uuid.UUID
    comment_id: uuid.UUID
    subject: str
    body: str
    author: str
    item: mailrender.ItemMail
    recipients: tuple[Recipient, ...]


async def recipients_for(session: AsyncSession, item_id: uuid.UUID) -> tuple[Recipient, ...]:
    """Every external person on this issue's mail thread (RADD-968, RADD-980).

    Users are reached by notify's mailer, off the notification rows that already
    passed `item.read`, the relation gate, the internal-comment filter and the
    per-user mute. Mailing them from here as well was the duplicate fan-out
    RADD-968 deleted.

    **It reads the plural seam since RADD-980.** A customer CCs their colleague,
    or the colleague replies instead; both are contacts on the item, and
    answering only the primary meant one of the people who asked never heard
    back — an outcome nothing surfaced, because a reply that WAS sent looks
    identical to a reply that was sent to everyone.

    One guard remains, and it is applied PER ADDRESS rather than to the set: an
    address belonging to an ACTIVE user is skipped, because a staff member who
    once raised a ticket by email is a contact AND a watcher and would otherwise
    get the same comment twice, once addressed as a customer. Per address is the
    part that changed — a single staff contact used to silence the whole reply.
    """
    contacts = await service.contacts_for_item(session, item_id)
    recipients: list[Recipient] = []
    for contact in contacts:
        # `get_user_by_email` lowercases; contacts are stored lowercased on write.
        user = await auth.get_user_by_email(session, contact.email)
        if user is not None and user.active:
            continue
        recipients.append(Recipient(contact.email, contact.name, MailRecipientKind.REQUESTER))
    return tuple(recipients)


def render(reply: OutboundReply, recipient: Recipient) -> mailrender.RenderedMail:
    """The text+html THIS recipient sees. Pure — the composition tests call it
    directly, which is how the outbound path finally got any at all."""
    reason = REPLY_REASON_TEMPLATES[recipient.kind].format(key=reply.item.key)
    return mailrender.comment_reply(
        reply.item, author=reply.author, body=reply.body, reason=reason
    )
