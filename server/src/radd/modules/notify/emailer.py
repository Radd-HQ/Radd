"""Email digests: one message per user batching their unemailed INBOX rows.

The slower half of the pair with `mailer.py`: rows the verdict marked `email`
are mailed individually and stamped, and this selection (`emailed_at IS NULL`)
skips them. `inbox IS TRUE` because an email-only row is the mailer's to send;
batching it here too could double-send on a racing tick — so this loop is not a
safety net for email-only rows (docs/specs/118-notification-rules.md).

Sent through `mailer.send_plain` → the `MAIL_TRANSPORT` socket; no transport
means pending rows are stamped undeliverable. Wording is `lines.py`.
"""

import logging
import uuid
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth

from . import lines, mailer, retry, service, transport as mail
from .models import Notification
from radd.clock import utcnow

logger = logging.getLogger(__name__)

DIGEST_SUBJECT_TEMPLATE = "[Radd] {count} new notification{plural}"


def compose(notifications: list[Notification], actor_names: dict[uuid.UUID, str]) -> mailrender.RenderedMail:
    """One user's pending notifications as a digest. Pure given its arguments."""
    return mailrender.digest(
        [lines.entry(notification, actor_names) for notification in notifications],
        inbox=mailrender.inbox_url(settings.app_base_url),
        preferences=mailer.preferences_url(),  # RADD-985: where it is turned off
    )


async def run_once() -> int:
    """One loop tick. Returns how many digests went out."""
    async with SessionLocal() as session:
        sent = await run_batch(session)
        await session.commit()
        return sent


async def run_batch(session: AsyncSession) -> int:
    """One digest per user with pending rows; read/stale rows are stamped unsent.
    The caller owns the commit (`mailer.run_batch`'s shape)."""
    transport = mail.mail_transport()
    if transport is not None and not await transport.configured(session):
        # Unconfigured is a WAIT (an admin is one form away); no transport at
        # all is not, and falls through to the stamp below.
        return 0
    now = utcnow()
    cutoff = now - timedelta(hours=settings.notify_email_max_age_hours)
    sent = 0
    result = await session.execute(
        select(Notification)
        .where(
            Notification.inbox.is_(True),
            Notification.emailed_at.is_(None),
            # RADD-997: a row this loop failed on waits out its backoff here too.
            or_(
                Notification.email_next_try.is_(None),
                Notification.email_next_try <= now,
            ),
        )
        .order_by(Notification.user_id, Notification.id)
    )
    rows = list(result.scalars())
    if not rows:
        return 0
    if transport is None:
        # RADD-1385: no digest without a transport; the backlog drains as it
        # does for someone who opted out, rather than waiting for one.
        await mailer.record_undeliverable(session, rows, mail.NotificationMailKind.DIGEST)
        return 0
    by_user: dict[uuid.UUID, list[Notification]] = defaultdict(list)
    for row in rows:
        by_user[row.user_id].append(row)
    users = await auth.users_by_ids(session, set(by_user))
    actor_names = await mailer._actor_names(session, rows)
    digest_off = await service.digest_disabled_users(session, set(by_user))
    for user_id, notifications in by_user.items():
        user = users.get(user_id)
        pending = [
            n for n in notifications if n.read_at is None and n.created_at >= cutoff
        ]
        if service.mailable_user(user):
            from .authorization import notification_readable

            allowed = []
            for notification in pending:
                if await notification_readable(session, notification, user):
                    allowed.append(notification)
                else:
                    notification.emailed_at = now
            pending = allowed
        # Opted out or not a mailbox: the rows are still stamped below.
        if user_id not in digest_off and service.mailable_user(user) and pending:
            message = compose(pending, actor_names)
            delivered = await mailer.send_plain(
                session,
                transport,
                user.email,
                user.name,
                DIGEST_SUBJECT_TEMPLATE.format(
                    count=len(pending), plural="" if len(pending) == 1 else "s"
                ),
                message,
                # The mailer's report policy over a batch: the FRESHEST row decides.
                failure=retry.failure_report(min(row.email_attempts for row in pending)),
                headers=mailrender.unsubscribe_headers(mailer.preferences_url()),
            )
            if delivered:
                sent += 1
            else:
                logger.warning("notify: digest send to %s failed", user.email)
                # RADD-997: the mailer's ladder and terminal stamp; the transport
                # never raises, so one bad address cannot cost the batch.
                for row in pending:
                    if retry.record_failure(row, now):
                        row.emailed_at = now
                continue
        await session.execute(
            update(Notification)
            .where(Notification.id.in_([n.id for n in notifications]))
            .values(emailed_at=now)
        )
    return sent
