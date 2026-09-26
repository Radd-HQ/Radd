"""WHO an outbound reply goes to, and WHAT it says (RADD-955/967/968). Only the
external contacts: users are mailed by notify through their own permission-gated
rows, so this leg serves the one recipient notify cannot have."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.modules.auth import service as auth

from . import service
from .transport import MailAttachment
from .types import REPLY_REASON_TEMPLATE, SentMailKind


@dataclass(frozen=True)
class Recipient:
    email: str
    name: str = ""


@dataclass(frozen=True)
class OutboundReply:
    """One planned reply: the INGREDIENTS (the body is rendered per recipient).
    Threading is not among them — the transport resolves it at send time, so
    nothing here can go stale between planning and delivery."""

    item_id: uuid.UUID
    comment_id: uuid.UUID
    subject: str
    body: str
    author: str
    item: mailrender.ItemMail
    recipients: tuple[Recipient, ...]

    #: A reply CONTINUES the requester's thread, so the stored subject wins
    #: (read off every `outbound.OutboundPlan`).
    pin_subject: bool = False
    kind: SentMailKind = SentMailKind.REPLY

    async def prepare(self, session: AsyncSession) -> tuple["OutboundReply | None", tuple[MailAttachment, ...]]:
        """The body as it is NOW, not as the event excerpt had it (RADD-988): a
        comment that turned internal or was deleted since planning sends
        nothing, and its inline images ride along only from approved storage
        hosts. Returns the reply to render plus the attachments to send."""
        from radd.modules.comments import service as comments

        from . import attachments

        body = await comments.public_reply_body(session, self.comment_id, self.item_id)
        if body is None:
            return None, ()
        body, images = await attachments.prepare(session, self.item_id, body)
        return replace(self, body=body), images

    def render(self, recipient: Recipient) -> mailrender.RenderedMail:
        return render(self, recipient)


async def recipients_for(session: AsyncSession, item_id: uuid.UUID) -> tuple[Recipient, ...]:
    """Every external contact on this issue's mail thread (RADD-968/980).

    Users are notify's to mail. The one guard is PER ADDRESS: an address
    belonging to an active user is skipped, so a staff member who once emailed
    in does not get the comment twice (once as a customer).
    """
    contacts = await service.contacts_for_item(session, item_id)
    recipients: list[Recipient] = []
    for contact in contacts:
        # `get_user_by_email` lowercases; contacts are stored lowercased on write.
        user = await auth.get_user_by_email(session, contact.email)
        if user is not None and user.active:
            continue
        recipients.append(Recipient(contact.email, contact.name))
    return tuple(recipients)


def render(reply: OutboundReply, recipient: Recipient) -> mailrender.RenderedMail:
    """The text+html THIS recipient sees. Pure."""
    del recipient  # one wording for every contact on the thread
    reason = REPLY_REASON_TEMPLATE.format(key=reply.item.key)
    return mailrender.comment_reply(
        reply.item, author=reply.author, body=reply.body, reason=reason
    )
