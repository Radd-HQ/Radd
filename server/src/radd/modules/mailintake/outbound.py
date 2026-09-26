"""Outbound mail to the external requester (spec 62, RADD-955/968/982).

One consumer ships two messages — a public comment relayed as a reply
(`reply.py`) and the resolution notice (`resolved.py`) — through the
`OutboundPlan` protocol. Users are notify's to mail; this leg exists because a
requester has no account and so no notification row.

Head-seeded cursor (`events.runner.run_head_seeded`), committed BEFORE sending:
for email a dropped reply beats a duplicate, and enabling a sender later
replays nothing.
"""

import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.comments import service as comments
from radd.modules.comments.types import CommentEvent, CommentOrigin, CommentVisibility
from radd.modules.events import runner
from radd.modules.events.service import Event
from radd.modules.items import service as items
from radd.modules.items.enums import ItemEvent
from radd.modules.projects import service as projects_service

from . import resolved, service
from .reply import OutboundReply, Recipient, recipients_for
from .transport import MailAttachment
from .types import OUTBOUND_BATCH, OUTBOUND_CONSUMER_NAME, REPLY_SUBJECT_TEMPLATE, SentMailKind

logger = logging.getLogger(__name__)

#: Attribution for a comment with no resolvable author (an upstream bug, but an
#: empty name is a broken sentence in someone's mailbox).
UNKNOWN_AUTHOR = "Someone"


class OutboundPlan(Protocol):
    """What this consumer needs of a planned message — including `pin_subject`, so
    the consumer never has to know which message opens its own topic."""

    item_id: uuid.UUID
    subject: str
    comment_id: uuid.UUID | None
    pin_subject: bool
    kind: SentMailKind
    recipients: tuple[Recipient, ...]

    async def prepare(self, session: AsyncSession) -> tuple["OutboundPlan | None", tuple[MailAttachment, ...]]:
        """Materialise what delivery needs: the reply re-reads its comment (RADD-988 —
        it may have turned internal or gone since planning). None = nothing to send."""
        ...

    def render(self, recipient: Recipient) -> mailrender.RenderedMail: ...


def should_reply(*, has_recipients: bool, visibility: str, origin: str | None) -> bool:
    """Pure send decision: someone to mail, the comment is PUBLIC, and it did not
    come FROM the requester's mail (the inbound echo — the first half of a loop).
    Decided by ORIGIN, not author (RADD-1318), so an automation's public comment
    is relayed like anyone's.
    """
    if not has_recipients:
        return False
    if visibility != CommentVisibility.PUBLIC.value:
        return False
    return origin != CommentOrigin.INBOUND_MAIL


async def _plan(session: AsyncSession, event: Event) -> OutboundPlan | None:
    """Which planner, if any, claims this event — after the shared
    `outbound_configured` gate (unconfigured still advances the cursor)."""
    if not await service.outbound_configured(session):
        return None  # unconfigured = advance silently, plan nothing
    if event.event_type == CommentEvent.CREATED.value:
        return await _plan_reply(session, event)
    if event.event_type == ItemEvent.UPDATED.value:
        return await resolved.plan(session, event)
    return None


async def run_once() -> int:
    return await runner.run_head_seeded(
        OUTBOUND_CONSUMER_NAME, batch_size=OUTBOUND_BATCH, plan=_plan, deliver=_deliver_all
    )


async def _plan_reply(session: AsyncSession, event: Event) -> OutboundReply | None:
    payload = event.payload or {}
    item = payload.get("item")
    if not item:
        # RADD-1247: a page comment (or a reply on one) has no requester to
        # mail — the parent is a page, so `item` is None by design.
        return None
    item_id = uuid.UUID(item["id"])  # RADD-922: the canonical ref
    item = await items.require_item(session, item_id)
    recipients = await recipients_for(session, item_id)
    if not should_reply(
        has_recipients=bool(recipients),
        visibility=payload.get("visibility", CommentVisibility.PUBLIC.value),
        origin=payload.get("origin"),
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
        # Only the OPENING subject; the transport prefers the thread's stored one.
        subject=REPLY_SUBJECT_TEMPLATE.format(key=key, title=item.title),
        body=body or payload.get("excerpt", ""),
        # The comment event's author ref (RADD-922).
        author=(payload.get("author") or {}).get("name") or UNKNOWN_AUTHOR,
        item=mailrender.ItemMail(key=key, title=item.title, base_url=settings.app_base_url),
        recipients=recipients,
    )


async def _deliver_all(plans: list[OutboundPlan]) -> None:
    for plan in plans:
        await _deliver(plan)


async def _deliver(plan: OutboundPlan) -> None:
    """Its own session per message: the cursor is already committed (at-most-once)."""
    async with SessionLocal() as session:
        prepared, images = await plan.prepare(session)
        for recipient in prepared.recipients if prepared is not None else ():
            # Composed PER RECIPIENT (RADD-967).
            message = prepared.render(recipient)
            await service.send_item_mail(
                session,
                item_id=plan.item_id,
                to_address=recipient.email,
                to_name=recipient.name,
                subject=plan.subject,
                text=message.text,
                html=message.html,
                comment_id=prepared.comment_id,
                pin_subject=prepared.pin_subject,
                attachments=images,
                kind=prepared.kind,
            )
        await session.commit()
