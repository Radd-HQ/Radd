"""Outbound comment mail (spec 62, rebuilt in RADD-955).

A comment on an issue emails the people following it, in a message their client
threads under the original rather than stacking as a new conversation.

Cursor idiom = the shared head-seeded scaffold (`events.runner.run_head_seeded`):
consumer offset `mailintake.outbound`, first start seeds AT THE STREAM HEAD (a
requester must never be mailed the historical backlog), and the cursor is
committed BEFORE sending — for email, a dropped reply beats a duplicate. With no
sender configured the consumer still advances, so enabling SMTP later does not
replay weeks of comments.

**Two things changed from spec 62 and both were silent failures:**

*Recipients.* It mailed exactly one address — the item's `mail_contact` — so an
internal commenter's reply reached the external requester and nobody else on the
ticket. Recipients are now the item's participants (reporter + previous
commenters + watchers) minus the author, over notify's existing watcher set,
plus the contact when there is one.

*Stored ids.* It set `In-Reply-To` from `contact.last_message_id` — the last
INBOUND id — and stored nothing it sent. So when a requester replied, their
`In-Reply-To` named a message Radd had no record of, and threading fell through
to the subject key. Every outbound message now goes into `mail_messages`, keyed
by **the id the sender reports having actually used** (`MailSender.send`'s return
value), not the one composed here.

RADD-967 moved the recipient set and the message body into `reply.py` (over
`radd.mailrender`): the reply used to be the bare comment text, so a watcher got
a paragraph with no author, no issue and no link. This file is now the consumer
— cursor, sender, delivery, outcome events.
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
from radd.modules.events import runner, service as events
from radd.modules.events.service import Event
from radd.modules.items import service as items
from radd.modules.projects import service as projects_service

from . import registry, threading
from .providers import OutboundMessage
from .reply import OutboundReply, recipients_for, render
from .senders import SmtpSender
from .types import (
    OUTBOUND_BATCH,
    OUTBOUND_CONSUMER_NAME,
    REPLY_SUBJECT_TEMPLATE,
    MailDirection,
    MailEntity,
    MailEvent,
    MailSenderKind,
)

logger = logging.getLogger(__name__)

#: What a comment with no resolvable author is attributed to. An event whose
#: `author` ref is missing is a bug upstream, but "commented" with an empty name
#: in front of it is a broken sentence in someone's mailbox.
UNKNOWN_AUTHOR = "Someone"


def should_reply(*, has_recipients: bool, visibility: str, actor_id: uuid.UUID | None) -> bool:
    """Pure send decision: someone to mail AND the comment is PUBLIC AND a real
    (non-SYSTEM) author. The SYSTEM gate is what stops inbound-mail comments and
    automation comments from echoing straight back out — the first half of a
    mail loop, closed here rather than left to the RADD-957 guards."""
    if not has_recipients:
        return False
    if visibility != CommentVisibility.PUBLIC.value:
        return False
    if actor_id is None or actor_id == SYSTEM_ACTOR_ID:
        return False
    return True


async def _sender(session: AsyncSession):
    """The configured `MailSender`, built from its ROW (RADD-958).

    Returns (sender, row) or (None, None). A kind maps to an implementation
    here and nowhere else, which is what makes a Gmail adapter a class plus a
    row rather than an edit to this module.
    """
    row = await registry.default_sender(session)
    if row is None:
        return None, None
    if row.kind == MailSenderKind.SMTP.value:
        return SmtpSender(row), row
    logger.warning("mailintake: no sender implementation for kind %r", row.kind)
    return None, None


async def _plan(session: AsyncSession, event: Event) -> OutboundReply | None:
    sender, _ = await _sender(session)
    if sender is None:  # unconfigured = advance silently, plan nothing
        return None
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
    recipients = await recipients_for(session, item_id, event.actor_id)
    if not should_reply(
        has_recipients=bool(recipients),
        visibility=payload.get("visibility", CommentVisibility.PUBLIC.value),
        actor_id=event.actor_id,
    ):
        return None
    project = await projects_service.get_project(session, item.project_id)
    key = f"{project.key}-{item.number}"
    # Byte-stable for the thread's whole life: a renamed issue must not split the
    # conversation in every participant's client.
    original = await threading.thread_subject(session, item_id)
    subject = (
        f"Re: {original}" if original and not original.lower().startswith("re:")
        else original or REPLY_SUBJECT_TEMPLATE.format(key=key, title=item.title)
    )
    chain = await threading.thread_chain(session, item_id)
    # The event excerpt is capped at 200 chars — fetch the full body via the seam.
    comment_id = uuid.UUID(event.entity_id)
    body = await comments.comment_body(session, comment_id)
    return OutboundReply(
        item_id=item_id,
        comment_id=comment_id,
        subject=subject,
        body=body or payload.get("excerpt", ""),
        # The author ref the comment event has always carried (RADD-922) and
        # this consumer never read — which is why a reply arrived as an
        # unattributed paragraph.
        author=(payload.get("author") or {}).get("name") or UNKNOWN_AUTHOR,
        item=mailrender.ItemMail(key=key, title=item.title, base_url=settings.app_base_url),
        recipients=recipients,
        in_reply_to=chain[-1] if chain else None,
        references=tuple(chain),
    )


async def _deliver_all(replies: list[OutboundReply]) -> None:
    for reply in replies:
        await _deliver(reply)


async def _deliver(reply: OutboundReply) -> None:
    async with SessionLocal() as session:
        sender, row = await _sender(session)
    if sender is None or row is None:
        return
    headers = {
        # Plain `help@`, no token: sub-addressing is stripped or rewritten by
        # exactly the corporate systems this feature targets (RADD-954).
        "Reply-To": row.reply_to or row.from_address,
    }
    if reply.in_reply_to:
        headers["In-Reply-To"] = reply.in_reply_to
    if reply.references:
        headers["References"] = " ".join(reply.references)

    sent_ids: list[str] = []
    delivered: list[str] = []
    failed: list[str] = []
    for recipient in reply.recipients:
        try:
            # Composed PER RECIPIENT: the footer says why this address is on the
            # thread, and a watcher and the external requester are on it for
            # different reasons (RADD-967).
            message = render(reply, recipient)
            sent = await sender.send(
                OutboundMessage(
                    to_address=recipient.email,
                    to_name=recipient.name,
                    subject=reply.subject,
                    body=message.text,
                    html_body=message.html,
                    headers=headers,
                )
            )
            delivered.append(recipient.email)
            if sent:
                sent_ids.append(sent)
        except Exception:
            # Log and move on — one unreachable address must not cost the others
            # their copy, and a reply is not worth a retry queue.
            logger.exception("mailintake: outbound reply to %s failed (dropped)", recipient.email)
            failed.append(recipient.email)

    await _emit_outcome(reply, delivered=delivered, failed=failed)
    if not sent_ids:
        return
    # Store what the SENDER SAID it used, not what we composed (RADD-955). SMTP
    # honours a client-set id; the Gmail API replaces it. Storing an intended
    # value the provider did not use makes every reply arrive unthreaded and
    # open a duplicate issue — days later, with nothing raised anywhere.
    #
    # One row per distinct id: a fan-out to five people is five messages, and a
    # reply may quote any of them.
    async with SessionLocal() as session:
        for message_id in dict.fromkeys(sent_ids):
            await threading.record(
                session,
                message_id=message_id,
                item_id=reply.item_id,
                direction=MailDirection.OUTBOUND,
                subject=reply.subject,
                comment_id=reply.comment_id,
            )
        await session.commit()


async def _emit_outcome(
    reply: OutboundReply, *, delivered: list[str], failed: list[str]
) -> None:
    """Report what the channel did (RADD-960).

    A failure here is currently a log line and nothing else, which means "the
    customer never got the reply" is invisible to every screen and every rule.
    `mail.failed` is item-scoped so a rule can flag the ticket — that is the
    whole point of emitting it rather than logging harder.

    Its own session: the consumer's cursor is already committed by this point
    (at-most-once, by design), so there is no transaction left to join.
    """
    if not delivered and not failed:
        return
    async with SessionLocal() as session:
        for event_type, addresses in (
            (MailEvent.SENT, delivered),
            (MailEvent.FAILED, failed),
        ):
            if not addresses:
                continue
            await events.emit(
                session,
                event_type=event_type,
                entity_type=MailEntity.MAIL,
                entity_id=reply.item_id,
                subjects={"item": reply.item_id},
                payload={
                    "recipients": addresses,
                    "recipient_count": len(addresses),
                    "subject": reply.subject,
                    # No body, for the reason in intake._mail_facts.
                },
            )
        await session.commit()
