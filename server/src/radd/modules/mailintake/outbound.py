"""Outbound comment replies (spec 62): an outbox consumer emailing a contact's
item PUBLIC comments back to them as `Re: [KEY] title`.

Cursor idiom = the shared head-seeded scaffold (`events.runner.run_head_seeded`):
consumer offset `mailintake.outbound`, first start seeds AT THE STREAM HEAD (a
requester must never be mailed the historical comment backlog), and the cursor
is committed BEFORE sending — for email, a dropped reply beats a duplicate.
With SMTP unconfigured the consumer still advances — enabling SMTP later must
not replay weeks of comments.

The send decision is the pure `should_reply` (tested): the item must have a
contact, the comment must be PUBLIC, and the actor must not be the SYSTEM actor
— the SYSTEM gate keeps inbound-mail comments and automation comments from
echoing back out.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd import smtp
from radd.config import settings
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.comments.types import CommentEvent, CommentVisibility
from radd.modules.events import runner
from radd.modules.events.service import Event
from radd.modules.items import service as items
from radd.modules.projects import service as projects_service

from . import service
from .types import OUTBOUND_BATCH, OUTBOUND_CONSUMER_NAME, REPLY_SUBJECT_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboundReply:
    email: str
    name: str
    subject: str
    body: str
    in_reply_to: str | None  # the contact's last inbound Message-ID, when held


def should_reply(*, has_contact: bool, visibility: str, actor_id: uuid.UUID | None) -> bool:
    """Pure send decision (spec 62): contact present AND comment PUBLIC AND a real
    (non-SYSTEM) author. No actor (clock/engine events) never replies either."""
    if not has_contact:
        return False
    if visibility != CommentVisibility.PUBLIC.value:
        return False
    if actor_id is None or actor_id == SYSTEM_ACTOR_ID:
        return False
    return True


async def _plan(session: AsyncSession, event: Event) -> OutboundReply | None:
    if not settings.smtp_host:  # unconfigured = advance silently, plan nothing
        return None
    if event.event_type != CommentEvent.CREATED.value:
        return None
    return await _plan_reply(session, event)


async def _deliver_all(replies: list[OutboundReply]) -> None:
    for reply in replies:
        await _deliver(reply)


async def run_once() -> int:
    return await runner.run_head_seeded(
        OUTBOUND_CONSUMER_NAME, batch_size=OUTBOUND_BATCH, plan=_plan, deliver=_deliver_all
    )


async def _plan_reply(session: AsyncSession, event: Event) -> OutboundReply | None:
    payload = event.payload or {}
    # RADD-922: the canonical ref every item-scoped event carries.
    item_id = uuid.UUID(payload["item"]["id"])
    contact = await service.contact_for_item(session, item_id)
    if not should_reply(
        has_contact=contact is not None,
        visibility=payload.get("visibility", CommentVisibility.PUBLIC.value),
        actor_id=event.actor_id,
    ):
        return None
    assert contact is not None  # narrowed by should_reply
    item = await items.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    # The event excerpt is capped at 200 chars — fetch the full body via the seam.
    body = await comments.comment_body(session, uuid.UUID(event.entity_id))
    return OutboundReply(
        email=contact.email,
        name=contact.name,
        subject=REPLY_SUBJECT_TEMPLATE.format(key=f"{project.key}-{item.number}", title=item.title),
        body=body or payload.get("excerpt", ""),
        in_reply_to=contact.last_message_id,
    )


async def _deliver(reply: OutboundReply) -> None:
    headers = (
        {"In-Reply-To": reply.in_reply_to, "References": reply.in_reply_to}
        if reply.in_reply_to
        else None
    )
    try:
        await asyncio.to_thread(
            smtp.send_message,
            reply.email,
            reply.subject,
            reply.body,
            to_name=reply.name,
            headers=headers,
        )
    except Exception:
        # Log + move on — a reply is not worth a retry queue (googlechat precedent);
        # the requester still gets subsequent replies.
        logger.exception("mailintake: outbound reply to %s failed (dropped)", reply.email)
