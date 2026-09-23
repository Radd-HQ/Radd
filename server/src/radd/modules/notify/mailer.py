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

**What gets mailed is the ROW's own verdict** (spec 118). RADD-686 filtered each
candidate in Python against its recipient's `email_types`, arguing the predicate
was per-user and so could not be SQL. It could not — while the only thing a row
remembered was its TYPE. That is also why the mailer could never honour a scoped
preference: it had no way to know whether a row reached its recipient because
they were assigned the issue or because they had subscribed to the project, so
"email me about my own work, digest the rest" was unanswerable here. The
decision is made once, at the write, by the code that still knows which relation
produced the row; this loop reads `notifications.email` and the whole per-user
pass is gone.

Rows whose verdict is inbox-only are never selected and stay unstamped, so the
digest takes them — that is what makes "inbox only" a channel choice rather than
a mute.

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
from collections.abc import Mapping
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
from radd.modules.mailintake.types import MailFailureReport

from . import lines, retry, service
from .authorization import notification_readable
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
    rows = await _pending(session)
    if not rows:
        return 0
    if not await can_send(session):
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
            row,
            user,
            actor_names,
            failure=retry.failure_report(row.email_attempts),
        ):
            sent += 1
            stamped.append(row.id)
        elif retry.record_failure(row, now):
            # RADD-997: a DELIVERY failure is still worth retrying — one relay
            # blip must not lose the message — but it now costs the row its
            # place in the queue, and the ladder ends. Before this, "unstamped"
            # meant "selected again in five seconds", for a day.
            stamped.append(row.id)
    if stamped:
        await session.execute(
            update(Notification).where(Notification.id.in_(stamped)).values(emailed_at=now)
        )
    return sent


async def _pending(session: AsyncSession) -> list[Notification]:
    """Rows whose own verdict says EMAIL, unemailed, unread and recent.

    UNREAD because a notification you have already opened is not worth an email;
    RECENT (the digest's own `notify_email_max_age_hours`) because a worker that
    was down for a week must not empty the backlog into everyone's mailbox one
    message at a time. Stale rows are left for the digest, which stamps them.

    NOT BACKED OFF (RADD-997): a row that has failed is invisible until its
    `email_next_try`. In SQL rather than in the loop deliberately — a Python
    skip would let a handful of failing rows fill `notify_mail_batch` and starve
    the healthy ones behind them, which is the shape the incident had.

    **`email IS TRUE` replaces a per-recipient Python filter** (spec 118).
    RADD-686 argued the predicate could not be SQL because it was per-user, so a
    type filter "could only be the union of everybody's". That was true while the
    only thing a row remembered was its TYPE — and it is why the mailer could
    never honour a scoped preference: it had no way to know whether this row
    reached its recipient because they were assigned it or because they had
    subscribed to the project. The decision is made once, at the write, by the
    code that still knows; here it is a column.
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


def _mail_transport():
    """mailintake's transport seam, or None. Deferred + feature-detected: the
    module loads AFTER notify and may be disabled — the shape
    `consumer.recipient_ids` uses for participants."""
    try:
        from radd.modules.mailintake import service as mailintake
    except ImportError:
        return None
    return mailintake


async def can_send(session: AsyncSession) -> bool:
    """Is there anywhere to send FROM? Asked once per tick, not once per row:
    resolving the sender is a query. Public because the digest loop asks the
    same question and asking it a second way is how the two channels came to
    disagree about whether the instance had a relay (RADD-983)."""
    transport = _mail_transport()
    if transport is None:
        return bool(settings.smtp_host)
    return await transport.outbound_configured(session)


async def _send(
    session: AsyncSession,
    notification: Notification,
    user: User,
    actor_names: dict[uuid.UUID, str],
    *,
    failure: MailFailureReport = MailFailureReport.REPORT,
) -> bool:
    """Compose and deliver one notification. True when it went out.

    `failure` is passed straight to the transport and is the whole of
    RADD-997's event half: the transport reports every send's outcome, which is
    right for its other callers (a reply, an ack and a survey are each sent
    once), and wrong for a loop that will try the same message again in a
    minute. The RETRY is what makes a failure uninteresting, and the retry lives
    here — so the suppression does too, rather than teaching the transport about
    ladders.
    """
    payload = notification.payload or {}
    key = payload.get("item_key") or ""
    item = mailrender.ItemMail(
        key=key,
        title=payload.get("item_title") or "",
        base_url=settings.app_base_url,
        comment=payload.get("comment_id") or None,
    )
    reason = lines.MAIL_REASON_TEMPLATE.format(key=key or "this issue")
    # RADD-985: every USER-addressed message says how to stop it — a footer link
    # and the `List-Unsubscribe` header the big providers rank senders on. The
    # recipient here is always an account holder (a notification row IS the
    # proof), which is what makes the preferences page the right target; the
    # requester-facing mail in `mailintake` never carries either.
    preferences = preferences_url()
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
    transport = _mail_transport()
    if transport is None or notification.item_id is None:
        return await _send_direct(user.email, user.name, subject, message, headers=headers)
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
            failure=failure,
            headers=headers,
        )
    )


def preferences_url() -> str:
    """Where this instance's recipients turn notification email off — the one
    URL both of notify's channels print and put in `List-Unsubscribe`, read
    off settings HERE so `mailrender` keeps reading none."""
    return mailrender.preferences_url(settings.app_base_url)


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


async def send_plain(
    session: AsyncSession,
    to_address: str,
    to_name: str,
    subject: str,
    message: mailrender.RenderedMail,
    *,
    failure: MailFailureReport = MailFailureReport.REPORT,
    headers: Mapping[str, str] | None = None,
) -> bool:
    """One message about NO single item, through the transport (RADD-983).

    The digest's send, shared with this file because "which relay, and is the
    outcome reported" is one answer for both of notify's email channels and was
    two before: the per-event mailer had ridden `send_item_mail` since
    RADD-968, while the digest still dialled `radd.smtp` off `settings.*` and
    therefore sent nothing at all on an instance configured only through
    Settings → Email.

    Itemless because a digest is about ten items — see `send_plain_mail`. The
    env-relay fallback below is what a disabled mailintake degrades to, exactly
    as `_send`'s does.

    The CALLER's session goes through, `_send`'s shape and for its reason: the
    `mail.sent` event belongs in the same transaction as the `emailed_at` stamp
    it describes. Letting the transport open its own would commit the event
    while the stamp was still uncommitted — two truths about one message, in the
    order that makes a rolled-back tick claim to have sent mail.
    """
    transport = _mail_transport()
    if transport is None:
        return await _send_direct(to_address, to_name, subject, message, headers=headers)
    return bool(
        await transport.send_plain_mail(
            session,
            to_address=to_address,
            to_name=to_name,
            subject=subject,
            text=message.text,
            html=message.html,
            failure=failure,
            headers=headers,
        )
    )


async def _send_direct(
    to_address: str,
    to_name: str,
    subject: str,
    message: mailrender.RenderedMail,
    *,
    headers: Mapping[str, str] | None = None,
) -> bool:
    """mailintake absent: the env relay, no threading. The digest's posture —
    a message with no conversation is better than no message."""
    if not settings.smtp_host:
        return False
    try:
        await asyncio.to_thread(
            smtp.send_message,
            to_address,
            subject,
            message.text,
            to_name=to_name,
            headers=headers,
            html_body=message.html,
        )
    except Exception:
        logger.exception("notify: mail to %s failed", to_address)
        return False
    return True
