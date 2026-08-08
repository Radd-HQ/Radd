"""Per-event notification mail: one fan-out, not two (RADD-968).

**The bug.** `mailintake.outbound` mailed `notify.watcher_ids` minus the author
on every public comment, while the INBOX fanned out over watchers ∪
participant-team members through `consumer._allowed` (item.read, the RADD-817
relation gate, the internal-comment filter). Two fan-outs, disagreeing:

- a participant-TEAM member got an inbox row and no email;
- a watcher who had since lost `item.read` still got the mail, because the mail
  path re-checked nothing;
- `muted_types` was in-app only — you could mute comments and keep getting them;
- and no event but `comment.created` ever mailed anyone at all.

**The fix is to mail the ROWS.** A notification row has already passed planner
precedence, the mute check and `_allowed`; re-planning from the event would be a
second copy of that policy, which is what drifted the first time. So this loop
reads notifications, not events — and every permission question is answered by
the row's existence.

**What gets mailed is now the RECIPIENT's answer** (RADD-686). Each row is kept
or dropped by its own user's `email_types` — `DEFAULT_EMAIL_TYPES` when they
have never saved a preference. That is why the filter is in Python rather than
in `_pending`'s WHERE: the predicate is per-user, so a SQL type filter could
only be the union of everybody's, which is every type as soon as two people
disagree. Dropped rows are left unstamped and the digest takes them, which is
what makes "inbox only" a channel choice rather than a mute.

Rows are stamped `emailed_at` on send, so the digest — whose selection is
already `emailed_at IS NULL` — never repeats what went out here. The two
channels dedup for free, with no new column.

Transport is `mailintake.service.send_item_mail`, reached DEFERRED and
feature-detected (the module loads later and may be disabled) — the shape
`consumer.recipient_ids` uses for participants. Absent, the env relay sends it
directly, which is the digest's existing posture; what is lost is threading, so
a reply to that copy opens a new ticket instead of landing on the issue.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender, smtp
from radd.clock import utcnow
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.comments import service as comments
from radd.modules.comments.types import CommentEvent
from radd.modules.events import service as events

from . import lines, service
from .models import Notification
from .types import NotificationType

logger = logging.getLogger(__name__)


async def run_once() -> int:
    """One loop tick. Returns how many messages went out."""
    async with SessionLocal() as session:
        sent = await run_batch(session)
        await session.commit()
        return sent


async def run_batch(session: AsyncSession) -> int:
    """Mail one batch of pending immediate-email notifications.

    The caller owns the commit — which is what lets a test drive the whole tick
    (selection, composition, delivery, stamping) against rows that were never
    committed, rather than re-implementing the loop's body in the test and
    proving only that the copy works.
    """
    rows = await _wanted(session, await _pending(session))
    if not rows:
        return 0
    if not await _can_send(session):
        # Nothing to send FROM. Leave the rows unstamped: the digest loop is
        # gated the same way and will stamp them when it can.
        return 0
    actor_names = await _actor_names(session, rows)
    users = await auth.users_by_ids(session, {row.user_id for row in rows})
    sent = 0
    stamped: list[uuid.UUID] = []
    for row in rows:
        user = users.get(row.user_id)
        if user is None or not user.active or not user.email:
            stamped.append(row.id)  # nowhere to send it; never retry it
            continue
        if await _send(session, row, user, actor_names):
            sent += 1
            stamped.append(row.id)
        # A DELIVERY failure leaves the row unstamped, so the next tick retries
        # it — bounded by `_pending`'s age window, after which the digest takes
        # it. Stamping here would lose the message to one relay blip.
    if stamped:
        await session.execute(
            update(Notification).where(Notification.id.in_(stamped)).values(emailed_at=utcnow())
        )
    return sent


async def _pending(session: AsyncSession) -> list[Notification]:
    """Unemailed, unread, recent rows — the candidates, before preferences.

    UNREAD because a notification you have already opened is not worth an email;
    RECENT (the digest's own `notify_email_max_age_hours`) because a worker that
    was down for a week must not empty the backlog into everyone's mailbox one
    message at a time. Stale rows are left for the digest, which stamps them.
    """
    cutoff = utcnow() - timedelta(hours=settings.notify_email_max_age_hours)
    result = await session.execute(
        select(Notification)
        .where(
            Notification.emailed_at.is_(None),
            Notification.read_at.is_(None),
            Notification.created_at >= cutoff,
        )
        .order_by(Notification.created_at, Notification.id)
        .limit(settings.notify_mail_batch)
    )
    return list(result.scalars())


async def _wanted(session: AsyncSession, rows: list[Notification]) -> list[Notification]:
    """The candidates their own recipient asked to be emailed about (RADD-686).

    One query for the whole batch, then a membership test per row. What is
    dropped here stays unstamped on purpose: the digest is the other half of the
    channel choice, not a fallback.
    """
    if not rows:
        return []
    wanted = await service.email_types_by_user(session, {row.user_id for row in rows})
    return [row for row in rows if row.type in wanted.get(row.user_id, frozenset())]


async def _actor_names(
    session: AsyncSession, rows: list[Notification]
) -> dict[uuid.UUID, str]:
    actors = await auth.users_by_ids(
        session, {row.actor_id for row in rows if row.actor_id is not None}
    )
    return {user_id: user.name for user_id, user in actors.items() if user.name}


def _mail_transport():
    """mailintake's transport seam, or None. Deferred + feature-detected: the
    module loads AFTER notify and may be disabled — the shape
    `consumer.recipient_ids` uses for participants."""
    try:
        from radd.modules.mailintake import service as mailintake
    except ImportError:
        return None
    return mailintake


async def _can_send(session: AsyncSession) -> bool:
    """Asked once per tick, not once per row: resolving the sender is a query."""
    transport = _mail_transport()
    if transport is None:
        return bool(settings.smtp_host)
    return await transport.outbound_configured(session)


async def _send(
    session: AsyncSession,
    notification: Notification,
    user: User,
    actor_names: dict[uuid.UUID, str],
) -> bool:
    """Compose and deliver one notification. True when it went out."""
    payload = notification.payload or {}
    key = payload.get("item_key") or ""
    item = mailrender.ItemMail(
        key=key, title=payload.get("item_title") or "", base_url=settings.app_base_url
    )
    reason = lines.MAIL_REASON_TEMPLATE.format(key=key or "this issue")
    entry = lines.entry(notification, actor_names)
    type_ = NotificationType(notification.type)
    body = (
        await _comment_body(session, notification)
        if type_ is NotificationType.COMMENTED
        else None
    )
    if body:
        message = mailrender.comment_reply(
            item,
            author=lines.actor_name(notification, actor_names),
            body=body,
            reason=reason,
        )
    else:
        # A comment deleted between the fan-out and this tick, or a type with no
        # body of its own: the digest's line on its own, with this recipient's
        # reason under it — never an empty quote block.
        message = mailrender.notice(entry, reason=reason)
    # A notification with no item (`page_updated`) has no key to bracket, so the
    # line names itself rather than shipping a subject of "[]".
    subject = (
        lines.MAIL_SUBJECT_TEMPLATE.format(key=key, title=item.title).strip()
        if key
        else (entry.subject or entry.headline)
    )
    transport = _mail_transport()
    if transport is None or notification.item_id is None:
        return await _send_direct(user, subject, message)
    return bool(
        await transport.send_item_mail(
            session,
            item_id=notification.item_id,
            to_address=user.email,
            to_name=user.name,
            subject=subject,
            text=message.text,
            html=message.html,
            comment_id=await _comment_id(session, notification),
        )
    )


async def _comment_id(session: AsyncSession, notification: Notification) -> uuid.UUID | None:
    """The comment this notification is about — or None when it is about none.

    The payload carries only a 200-char excerpt, so the comment has to be found
    through the outbox row the notification was fanned out from — `event_id` →
    the `comment.created` event, whose `entity_id` IS the comment.

    **The event-type check is load-bearing** (found by RADD-978). Every event
    carries an `entity_id`, and for the item family that id is the ITEM, so
    without it this function returned an item's uuid AS a comment id; the
    transport then wrote it to `mail_messages.comment_id` and the whole tick died
    on a foreign-key violation. It had never fired because the only rows anybody
    had mailed with an `event_id` set came from `comment.created` —
    `participant_added` is the first type mailed from a different event, and
    `assigned`, `state_changed` and a description `mentioned` (all reachable from
    the preference matrix, `assigned`/`mentioned` by default) were one saved
    preference away from the same crash.
    """
    if notification.event_id is None:
        return None
    event = await events.get_event(session, notification.event_id)
    if event is None or event.event_type != CommentEvent.CREATED.value:
        return None
    try:
        return uuid.UUID(event.entity_id)
    except (ValueError, TypeError):
        return None


async def _comment_body(session: AsyncSession, notification: Notification) -> str:
    """The FULL comment, not the excerpt — the same seam the consumer
    mention-scans through. Falls back to the excerpt if the comment is gone."""
    comment_id = await _comment_id(session, notification)
    body = await comments.comment_body(session, comment_id) if comment_id else None
    return body or (notification.payload or {}).get("excerpt") or ""


async def _send_direct(user: User, subject: str, message: mailrender.RenderedMail) -> bool:
    """mailintake absent: the env relay, no threading. The digest's posture —
    a message with no conversation is better than no message."""
    if not settings.smtp_host:
        return False
    try:
        await asyncio.to_thread(
            smtp.send_message,
            user.email,
            subject,
            message.text,
            to_name=user.name,
            html_body=message.html,
        )
    except Exception:
        logger.exception("notify: mail to %s failed", user.email)
        return False
    return True
