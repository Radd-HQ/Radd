"""WHO an outbound reply goes to, and WHAT it says (RADD-955, RADD-967).

Split out of `outbound.py`, which is the consumer that ships it: the cursor
idiom, the sender lookup and the delivery loop have nothing to do with the
recipient set, and both files were past the point where one screen showed
either concern whole.

Everything here is either a pure function or one lookup: `recipients_for` reads
the watcher set + the mail contact, `render` is pure and per-recipient. The
footer is the only thing that differs between copies — the whole reason a body
is composed per address rather than once (see `MailRecipientKind`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.auth import service as auth
from radd.modules.notify import service as notify

from . import service
from .types import REPLY_REASON_TEMPLATES, MailRecipientKind


@dataclass(frozen=True)
class Recipient:
    email: str
    name: str = ""
    #: Watcher unless proven otherwise — a Radd user is the ordinary case, and
    #: the external contact is added by exactly one line below.
    kind: MailRecipientKind = MailRecipientKind.WATCHER


@dataclass(frozen=True)
class OutboundReply:
    """One planned reply: the comment, and everyone it goes to.

    It carries the INGREDIENTS rather than a finished body, because the body is
    a function of the recipient (`render`).
    """

    item_id: uuid.UUID
    comment_id: uuid.UUID
    subject: str
    body: str
    author: str
    item: mailrender.ItemMail
    recipients: tuple[Recipient, ...]
    in_reply_to: str | None
    references: tuple[str, ...] = field(default_factory=tuple)


async def recipients_for(
    session: AsyncSession, item_id: uuid.UUID, author_id: uuid.UUID | None
) -> tuple[Recipient, ...]:
    """Everyone following this issue, minus whoever wrote the comment.

    Watchers already ARE the participant set: notify auto-watches the reporter,
    commenters and anyone added as a participant (spec 72), so reusing it keeps
    one fan-out mechanism rather than growing a second recipient model that
    would drift from the one deciding in-app notifications.
    """
    found: dict[str, Recipient] = {}
    for user_id in await notify.watcher_ids(session, item_id):
        if user_id == author_id or user_id == SYSTEM_ACTOR_ID:
            continue
        user = await auth.get_user(session, user_id)
        if user is None or not user.active or not user.email:
            continue
        found[user.email.lower()] = Recipient(email=user.email, name=user.name or "")
    # The external requester is not a user row, so they are never a watcher.
    # `setdefault`, so a staff member who also happens to be the contact keeps
    # their watcher wording rather than being addressed as a customer.
    contact = await service.contact_for_item(session, item_id)
    if contact is not None:
        found.setdefault(
            contact.email.lower(),
            Recipient(contact.email, contact.name, MailRecipientKind.REQUESTER),
        )
    return tuple(found.values())


def render(reply: OutboundReply, recipient: Recipient) -> mailrender.RenderedMail:
    """The text+html THIS recipient sees. Pure — the composition tests call it
    directly, which is how the outbound path finally got any at all."""
    reason = REPLY_REASON_TEMPLATES[recipient.kind].format(key=reply.item.key)
    return mailrender.comment_reply(
        reply.item, author=reply.author, body=reply.body, reason=reason
    )
