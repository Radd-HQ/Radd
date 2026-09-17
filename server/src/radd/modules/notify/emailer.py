"""Email digests: one email per user batching their unemailed notifications.

**Sends through the ONE transport since RADD-983** (`mailer.send_plain`, i.e.
`mailintake.service.send_plain_mail`, with the env relay as the fallback when
that module is not loaded). It used to dial `radd.smtp` itself and gate on
`settings.smtp_host`, which meant an instance configured entirely through
Settings → Email — sender ROWS, no `RADD_SMTP_*` — never sent a digest and said
nothing about it. Now the gate is `outbound_configured` (rows OR env) and every
failure is a `mail.failed` event as well as a log line.

The digest is deliberately the ITEMLESS half of the transport: it is about ten
issues, so there is nothing to thread it onto.

**What a line SAYS is `lines.py`; what it LOOKS like is `radd.mailrender`.** The
vocabulary used to live here (RADD-967 gave all nine types their own sentence,
where four had been serving nine) and moved out when RADD-968 gave notify a
second email channel — the per-event `mailer.py`. Two channels rendering the
same types from two files is how the four-sentence bug happens again.

**This loop is now the SLOWER half of a pair.** A row whose stored verdict says
`email` (spec 118 — the resolver decided it at the write, from the relation that
produced the row) is mailed individually within seconds by `mailer` and stamped
`emailed_at`; the selection below already skips stamped rows, so the dedup
between the two channels costs no new column and no new query. Everything the
verdict left inbox-only lands here — which is what makes "inbox only, digest me"
a real answer rather than silence.

**This loop digests the INBOX**, hence the `inbox IS TRUE` below: an email-only
row is the mailer's to send and it will stamp it either way (delivered, or
terminal after the retry ladder), so batching it here as well would mail the same
notification twice on the one tick where the two loops raced. The cost of that
choice is that this loop is not a safety net for an email-only row — see the
known issue in `docs/specs/118-notification-rules.md`.
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

from . import lines, mailer, retry, service
from .models import Notification
from radd.clock import utcnow

logger = logging.getLogger(__name__)

DIGEST_SUBJECT_TEMPLATE = "[Radd] {count} new notification{plural}"


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
    if not await mailer.can_send(session):
        # Rows OR env (RADD-983) — `settings.smtp_host` alone silenced every
        # digest on an instance configured through Settings → Email. Asked once
        # per tick, like the mailer's, because resolving the sender is a query.
        return 0
    now = utcnow()
    cutoff = now - timedelta(hours=settings.notify_email_max_age_hours)
    sent = 0
    result = await session.execute(
        select(Notification)
        .where(
            # Spec 118: a digest is a digest of your INBOX. An email-only row is
            # the per-event mailer's to send, and it will stamp it either way
            # (delivered, or terminal after the retry ladder) — batching it in
            # here as well would mail the same notification twice on the one
            # tick where the two loops raced.
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
        if service.mailable_user(user):
            from .authorization import notification_readable

            allowed = []
            for notification in pending:
                if await notification_readable(session, notification, user):
                    allowed.append(notification)
                else:
                    notification.emailed_at = now
            pending = allowed
        # Opted-out users — and, since RADD-996, service accounts and the system
        # actor — still get their rows stamped below (the backlog drains).
        if user_id not in digest_off and service.mailable_user(user) and pending:
            message = compose(pending, actor_names)
            delivered = await mailer.send_plain(
                session,
                user.email,
                user.name,
                DIGEST_SUBJECT_TEMPLATE.format(
                    count=len(pending), plural="" if len(pending) == 1 else "s"
                ),
                message,
                # The mailer's report policy, applied to a batch: the FRESHEST
                # row decides, so the first failure is reported, the retries in
                # between are silent, and the tick that exhausts every row's
                # ladder is the one marked given-up.
                failure=retry.failure_report(min(row.email_attempts for row in pending)),
            )
            if delivered:
                sent += 1
            else:
                logger.warning("notify: digest send to %s failed", user.email)
                # RADD-997: not "retried next interval" any more. This loop is
                # gentler than the mailer (300s, one message per user rather
                # than per row) but its retry was equally unbounded, so it takes
                # the same ladder — and the same terminal stamp, which is the
                # only thing that stops an undeliverable address being dialled
                # every five minutes for a day.
                #
                # The failure arrives as a False rather than an exception now
                # (RADD-983): the transport never raises, so one unreachable
                # address cannot cost the rest of the batch its digests.
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
