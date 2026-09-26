"""Per-event notification mail (RADD-968): mails notification ROWS, not events.

A row has already passed planner precedence, the channel verdict and
`consumer._allowed`; re-planning from the event would be a second copy of that
policy. Only rows whose stamped verdict says `email` are selected; inbox-only
rows are left for the digest. Sent rows are stamped `emailed_at`, which the
digest's selection already skips, so the two channels never double-send.

Delivery is the kernel `MAIL_TRANSPORT` socket (`transport.py`). With no
transport, pending rows are stamped undeliverable and the inbox is untouched.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.clock import utcnow
from radd.config import settings
from radd.db import SessionLocal
from radd.kernel.sockets import MailTransport
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.comments import service as comments
from radd.modules.comments.types import CommentEvent
from radd.modules.events import service as events

from . import lines, retry, service, transport as mail
from .authorization import notification_readable
from .models import Notification
from .transport import MailFailureReport, NotificationMail, NotificationMailKind
from .types import NotificationType

logger = logging.getLogger(__name__)


async def run_once() -> int:
    """One loop tick. Returns how many messages went out."""
    async with SessionLocal() as session:
        sent = await run_batch(session)
        await session.commit()
        return sent


async def run_batch(session: AsyncSession) -> int:
    """Mail one batch of pending immediate-email notifications. The caller owns
    the commit, so a test can drive the whole tick against uncommitted rows."""
    rows = await _pending(session)
    if not rows:
        return 0
    transport = mail.mail_transport()
    if transport is None:
        await record_undeliverable(session, rows, NotificationMailKind.NOTIFICATION)
        return 0
    if not await transport.configured(session):
        # Nothing to send FROM. Leave the rows unstamped: the digest loop is
        # gated the same way and will stamp them when it can.
        return 0
    actor_names = await _actor_names(session, rows)
    users = await auth.users_by_ids(session, {row.user_id for row in rows})
    now = utcnow()
    sent = 0
    stamped: list[uuid.UUID] = []
    for row in rows:
        user = users.get(row.user_id)
        if not service.mailable_user(user) or not await notification_readable(session, row, user):
            # Inactive, address-less, a spec-113 SERVICE account or the system
            # actor (RADD-996) — none of them a mailbox. Nowhere to send it;
            # never retry it.
            stamped.append(row.id)
            continue
        if await _send(
            session,
            transport,
            row,
            user,
            actor_names,
            failure=retry.failure_report(row.email_attempts),
        ):
            sent += 1
            stamped.append(row.id)
        elif retry.record_failure(row, now):
            # RADD-997: a delivery failure retries on the ladder; exhausted, stamp.
            stamped.append(row.id)
    if stamped:
        await session.execute(
            update(Notification).where(Notification.id.in_(stamped)).values(emailed_at=now)
        )
    return sent


async def _pending(session: AsyncSession) -> list[Notification]:
    """Rows whose stamped verdict says EMAIL, unemailed, unread and recent
    (`notify_email_max_age_hours` — a worker down for a week must not flush its
    backlog; stale rows are the digest's to stamp), and not backed off. The
    backoff is in SQL so failing rows cannot fill `notify_mail_batch` and starve
    healthy ones (RADD-997).
    """
    now = utcnow()
    cutoff = now - timedelta(hours=settings.notify_email_max_age_hours)
    result = await session.execute(
        select(Notification)
        .where(
            Notification.email.is_(True),
            Notification.emailed_at.is_(None),
            Notification.read_at.is_(None),
            Notification.created_at >= cutoff,
            or_(
                Notification.email_next_try.is_(None),
                Notification.email_next_try <= now,
            ),
        )
        .order_by(Notification.created_at, Notification.id)
        .limit(settings.notify_mail_batch)
    )
    return list(result.scalars())


async def _actor_names(
    session: AsyncSession, rows: list[Notification]
) -> dict[uuid.UUID, str]:
    actors = await auth.users_by_ids(
        session, {row.actor_id for row in rows if row.actor_id is not None}
    )
    return {user_id: user.name for user_id, user in actors.items() if user.name}


async def record_undeliverable(
    session: AsyncSession, rows: list[Notification], kind: NotificationMailKind
) -> None:
    """No transport: stamp the rows (the channel is finished with them — not a
    claim anything was sent) so a returning mail plugin cannot flush a backlog.
    The inbox half is untouched. Public: the digest records its rows the same way."""
    await session.execute(
        update(Notification)
        .where(Notification.id.in_([row.id for row in rows]))
        .values(emailed_at=utcnow())
    )
    logger.info(
        "notify: no mail transport registered — %d %s email(s) recorded undeliverable",
        len(rows),
        kind.value,
    )


async def _send(
    session: AsyncSession,
    transport: MailTransport,
    notification: Notification,
    user: User,
    actor_names: dict[uuid.UUID, str],
    *,
    failure: MailFailureReport = MailFailureReport.REPORT,
) -> bool:
    """Compose and deliver one notification; True when it went out. `failure` is
    the retry ladder's instruction to the transport (RADD-997)."""
    payload = notification.payload or {}
    key = payload.get("item_key") or ""
    item = mailrender.ItemMail(
        key=key,
        title=payload.get("item_title") or "",
        base_url=settings.app_base_url,
        comment=payload.get("comment_id") or None,
    )
    reason = lines.MAIL_REASON_TEMPLATE.format(key=key or "this issue")
    # RADD-985: user-addressed mail says how to stop it (footer + List-Unsubscribe);
    # requester-facing mail never does.
    preferences = preferences_url()
    entry = lines.entry(notification, actor_names)
    body = (
        await _comment_body(session, notification)
        if notification.type == NotificationType.COMMENTED
        else None
    )
    if body:
        message = mailrender.comment_reply(
            item,
            author=lines.actor_name(notification, actor_names),
            body=body,
            reason=reason,
            preferences=preferences,
        )
    else:
        # A comment deleted between the fan-out and this tick, or a type with no
        # body of its own: the digest's line on its own, with this recipient's
        # reason under it — never an empty quote block.
        message = mailrender.notice(entry, reason=reason, preferences=preferences)
    # A notification with no item (`page_updated`) has no key to bracket, so the
    # line names itself rather than shipping a subject of "[]".
    subject = (
        lines.MAIL_SUBJECT_TEMPLATE.format(key=key, title=item.title).strip()
        if key
        else (entry.subject or entry.headline)
    )
    headers = mailrender.unsubscribe_headers(preferences)
    # No item (a page): nothing to thread on, but still through the transport.
    return await transport.send(
        session,
        NotificationMail(
            to_address=user.email,
            to_name=user.name,
            subject=subject,
            text=message.text,
            html=message.html,
            kind=NotificationMailKind.NOTIFICATION,
            failure=failure,
            headers=headers,
            item_id=notification.item_id,
            comment_id=(
                await _comment_id(session, notification) if notification.item_id else None
            ),
        ),
    )


def preferences_url() -> str:
    """The one URL both channels print and put in `List-Unsubscribe` (read off
    settings here so `mailrender` reads none)."""
    return mailrender.preferences_url(settings.app_base_url)


async def _comment_id(session: AsyncSession, notification: Notification) -> uuid.UUID | None:
    """The comment this notification is about, or None — via `event_id` → the
    `comment.created` event, whose `entity_id` IS the comment. The event-type
    check is load-bearing (RADD-978): for item events `entity_id` is the ITEM,
    and passing it on as a comment id kills the tick on a foreign-key violation.
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
    """The FULL comment, falling back to the excerpt if the comment is gone."""
    comment_id = await _comment_id(session, notification)
    body = await comments.comment_body(session, comment_id) if comment_id else None
    return body or (notification.payload or {}).get("excerpt") or ""


async def send_plain(
    session: AsyncSession,
    transport: MailTransport,
    to_address: str,
    to_name: str,
    subject: str,
    message: mailrender.RenderedMail,
    *,
    failure: MailFailureReport = MailFailureReport.REPORT,
    headers: Mapping[str, str] | None = None,
) -> bool:
    """One message about NO single item, through the transport (RADD-983) — the
    digest's send. The CALLER's session goes through so `mail.sent` commits with
    the `emailed_at` stamp it describes, never before it.
    """
    return await transport.send(
        session,
        NotificationMail(
            to_address=to_address,
            to_name=to_name,
            subject=subject,
            text=message.text,
            html=message.html,
            kind=NotificationMailKind.DIGEST,
            failure=failure,
            headers=dict(headers or {}),
        ),
    )
