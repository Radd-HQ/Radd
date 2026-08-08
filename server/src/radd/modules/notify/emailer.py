"""Email digests: one email per user batching their unemailed notifications.

Sends through the shared `radd.smtp` helper in a thread — no new dependency; an
empty RADD_SMTP_HOST (the default) disables the loop entirely.

**What a line SAYS is `lines.py`; what it LOOKS like is `radd.mailrender`.** The
vocabulary used to live here (RADD-967 gave all nine types their own sentence,
where four had been serving nine) and moved out when RADD-968 gave notify a
second email channel — the per-event `mailer.py`. Two channels rendering the
same types from two files is how the four-sentence bug happens again.

**This loop is now the SLOWER half of a pair.** Rows whose type the recipient
put in their `email_types` (RADD-686) are mailed individually within seconds by
`mailer` and stamped `emailed_at`; the selection below already skips stamped
rows, so the dedup between the two channels costs no new column and no new
query. Everything else lands here — which is what makes "inbox only, digest me"
a real answer rather than silence.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd import mailrender, smtp
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth

from . import lines, retry, service
from .models import Notification
from radd.clock import utcnow

logger = logging.getLogger(__name__)

DIGEST_SUBJECT_TEMPLATE = "[Radd] {count} new notification{plural}"


def _send_digest(to_address: str, to_name: str, message: mailrender.RenderedMail, count: int) -> None:
    smtp.send_message(
        to_address,
        DIGEST_SUBJECT_TEMPLATE.format(count=count, plural="" if count == 1 else "s"),
        message.text,
        to_name=to_name,
        html_body=message.html,
    )


def compose(notifications: list[Notification], actor_names: dict[uuid.UUID, str]) -> mailrender.RenderedMail:
    """One user's pending notifications as a digest. Pure given its arguments —
    which is what makes "one distinct line per type" testable."""
    return mailrender.digest(
        [lines.entry(notification, actor_names) for notification in notifications],
        inbox=mailrender.inbox_url(settings.app_base_url),
    )


async def run_once() -> int:
    """One loop tick. Returns how many digests went out."""
    async with SessionLocal() as session:
        sent = await run_batch(session)
        await session.commit()
        return sent


async def run_batch(session: AsyncSession) -> int:
    """Send one digest per user with pending (unemailed, unread, recent) notifications.
    Already-read or too-old rows are stamped without sending so the backlog drains.

    The caller owns the commit, `mailer.run_batch`'s shape and for its reason: it
    is the only way a test can drive the real selection, composition, delivery
    and stamping instead of re-implementing the loop and proving the copy works.
    Until RADD-996 this loop had no end-to-end test at all — which is how it went
    on mailing service accounts beside the mailer.
    """
    if not settings.smtp_host:
        return 0
    now = utcnow()
    cutoff = now - timedelta(hours=settings.notify_email_max_age_hours)
    sent = 0
    result = await session.execute(
        select(Notification)
        .where(
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
    by_user: dict[uuid.UUID, list[Notification]] = defaultdict(list)
    for row in rows:
        by_user[row.user_id].append(row)
    users = await auth.users_by_ids(session, set(by_user))
    # Actor names by id, one query for the batch: `page_updated` notifications
    # never carried `actor_name` in their payload (pages writes its own), so
    # every wiki line read "Someone edited …".
    actors = await auth.users_by_ids(
        session, {row.actor_id for row in rows if row.actor_id is not None}
    )
    actor_names = {user_id: user.name for user_id, user in actors.items() if user.name}
    digest_off = await service.digest_disabled_users(session, set(by_user))
    for user_id, notifications in by_user.items():
        user = users.get(user_id)
        pending = [
            n for n in notifications if n.read_at is None and n.created_at >= cutoff
        ]
        # Opted-out users — and, since RADD-996, service accounts and the system
        # actor — still get their rows stamped below (the backlog drains).
        if user_id not in digest_off and service.mailable_user(user) and pending:
            message = compose(pending, actor_names)
            try:
                await asyncio.to_thread(
                    _send_digest, user.email, user.name, message, len(pending)
                )
                sent += 1
            except Exception:
                logger.exception("notify: digest send to %s failed", user.email)
                # RADD-997: not "retried next interval" any more. This loop is
                # gentler than the mailer (300s, one message per user rather
                # than per row) but its retry was equally unbounded, so it takes
                # the same ladder — and the same terminal stamp, which is the
                # only thing that stops an undeliverable address being dialled
                # every five minutes for a day.
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
