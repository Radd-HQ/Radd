"""Outbound comment mail to the external requester (spec 62, rebuilt RADD-955/968).

A public comment on a ticket that came in by email is mailed back to the person
who raised it, in a message their client threads under the original rather than
stacking as a new conversation.

Cursor idiom = the shared head-seeded scaffold (`events.runner.run_head_seeded`):
consumer offset `mailintake.outbound`, first start seeds AT THE STREAM HEAD (a
requester must never be mailed the historical backlog), and the cursor is
committed BEFORE sending — for email, a dropped reply beats a duplicate. With no
sender configured the consumer still advances, so enabling SMTP later does not
replay weeks of comments.

**RADD-968 narrowed the recipients to the contact.** This consumer used to mail
notify's watcher set too, a second fan-out that disagreed with the one deciding
the inbox (see `reply.recipients_for`). Users are now mailed by `notify.mailer`;
this file owns the leg notify structurally cannot: the requester has no account,
so no notification row can ever exist for them.

Delivery itself moved to `service.send_item_mail` — one transport, two callers
(this consumer and notify's mailer), so threading, the sender row, the recorded
Message-ID and the `mail.sent`/`mail.failed` events cannot drift apart.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.comments.types import CommentEvent, CommentVisibility
from radd.modules.events import runner
from radd.modules.events.service import Event
from radd.modules.items import service as items
from radd.modules.projects import service as projects_service

from . import service
from .reply import OutboundReply, recipients_for, render
from .types import OUTBOUND_BATCH, OUTBOUND_CONSUMER_NAME, REPLY_SUBJECT_TEMPLATE

logger = logging.getLogger(__name__)

#: What a comment with no resolvable author is attributed to. An event whose
#: `author` ref is missing is a bug upstream, but "commented" with an empty name
#: in front of it is a broken sentence in someone's mailbox.
UNKNOWN_AUTHOR = "Someone"


def should_reply(*, has_recipients: bool, visibility: str, actor_id: uuid.UUID | None) -> bool:
    """Pure send decision: someone to mail AND the comment is PUBLIC AND a real
    (non-SYSTEM) author. The SYSTEM gate is what stops inbound-mail comments and
    automation comments from echoing straight back out — the first half of a
    mail loop, closed here rather than left to the RADD-957 guards.

    The PUBLIC gate is also what keeps an internal comment away from the
    customer: notify mails internal comments to the users whose notification
    rows survived `comment.read_internal`, and this leg never sees them.
    """
    if not has_recipients:
        return False
    if visibility != CommentVisibility.PUBLIC.value:
        return False
    if actor_id is None or actor_id == SYSTEM_ACTOR_ID:
        return False
    return True


async def _plan(session: AsyncSession, event: Event) -> OutboundReply | None:
    if not await service.outbound_configured(session):
        return None  # unconfigured = advance silently, plan nothing
    if event.event_type != CommentEvent.CREATED.value:
        return None
    return await _plan_reply(session, event)


async def run_once() -> int:
    return await runner.run_head_seeded(
        OUTBOUND_CONSUMER_NAME, batch_size=OUTBOUND_BATCH, plan=_plan, deliver=_deliver_all
    )


async def _plan_reply(session: AsyncSession, event: Event) -> OutboundReply | None:
    payload = event.payload or {}
    item_id = uuid.UUID(payload["item"]["id"])  # RADD-922: the canonical ref
    item = await items.require_item(session, item_id)
    recipients = await recipients_for(session, item_id)
    if not should_reply(
        has_recipients=bool(recipients),
        visibility=payload.get("visibility", CommentVisibility.PUBLIC.value),
        actor_id=event.actor_id,
    ):
        return None
    project = await projects_service.get_project(session, item.project_id)
    key = f"{project.key}-{item.number}"
    # The event excerpt is capped at 200 chars — fetch the full body via the seam.
    comment_id = uuid.UUID(event.entity_id)
    body = await comments.comment_body(session, comment_id)
    return OutboundReply(
        item_id=item_id,
        comment_id=comment_id,
        # Only the OPENING subject: the transport prefers the thread's stored
        # one, so a rename cannot split the conversation.
        subject=REPLY_SUBJECT_TEMPLATE.format(key=key, title=item.title),
        body=body or payload.get("excerpt", ""),
        # The author ref the comment event has always carried (RADD-922) and
        # this consumer never read — which is why a reply arrived as an
        # unattributed paragraph.
        author=(payload.get("author") or {}).get("name") or UNKNOWN_AUTHOR,
        item=mailrender.ItemMail(key=key, title=item.title, base_url=settings.app_base_url),
        recipients=recipients,
    )


async def _deliver_all(replies: list[OutboundReply]) -> None:
    for reply in replies:
        await _deliver(reply)


async def _deliver(reply: OutboundReply) -> None:
    """Its own session per message: the consumer's cursor is already committed
    by this point (at-most-once, by design), so there is no transaction left to
    join and the transport opens what it needs."""
    async with SessionLocal() as session:
        for recipient in reply.recipients:
            # Composed PER RECIPIENT: the footer says why this address is on the
            # thread (RADD-967). Today that is one address, but the seam is the
            # same one notify uses for the watcher wording.
            message = render(reply, recipient)
            await service.send_item_mail(
                session,
                item_id=reply.item_id,
                to_address=recipient.email,
                to_name=recipient.name,
                subject=reply.subject,
                text=message.text,
                html=message.html,
                comment_id=reply.comment_id,
            )
        await session.commit()
