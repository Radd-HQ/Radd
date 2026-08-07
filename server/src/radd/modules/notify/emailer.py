"""Email digests: one email per user batching their unemailed notifications.

Sends through the shared `radd.smtp` helper in a thread — no new dependency; an
empty RADD_SMTP_HOST (the default) disables the loop entirely.

**What a line SAYS is decided here; what it LOOKS like is `radd.mailrender`**
(RADD-967). This module owns `NotificationType`, so the nine sentences belong
here — and until RADD-967 there were four: assigned, mentioned, state_changed,
and everything else collapsed into "commented", so an SLA breach, an approval
request, an automation's message and a wiki page edit all reached your mailbox
as "Someone commented" with a link to an issue that, for the last two, was not
even the thing that happened.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select, update

from radd import mailrender, smtp
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth

from . import service
from .models import Notification
from .types import NotificationType
from radd.clock import utcnow

logger = logging.getLogger(__name__)

#: No resolvable actor: a clock (SLA timers) or the system (automations) did it.
UNKNOWN_ACTOR = "Someone"

DIGEST_SUBJECT_TEMPLATE = "[Radd] {count} new notification{plural}"


def _headline(type_: NotificationType, actor: str, payload: dict) -> str:
    """The sentence for one notification. Every type gets its own — a shared
    fallback is how five of them ended up claiming someone commented."""
    if type_ is NotificationType.ASSIGNED:
        return f"{actor} assigned you"
    if type_ is NotificationType.MENTIONED:
        source = payload.get("source")
        return f"{actor} mentioned you in the {source}" if source else f"{actor} mentioned you"
    if type_ is NotificationType.STATE_CHANGED:
        return f"{actor} moved {payload.get('from') or '?'} → {payload.get('to') or '?'}"
    if type_ is NotificationType.COMMENTED:
        return f"{actor} commented"
    if type_ in (NotificationType.SLA_BREACH, NotificationType.SLA_DUE_SOON):
        state = "breached" if type_ is NotificationType.SLA_BREACH else "due soon"
        # `kind` (response/resolution) is absent on older rows — joined rather
        # than interpolated so its absence costs no double space.
        target = " ".join(filter(None, ("SLA", payload.get("kind"), "target", state)))
        return f"{target} ({payload.get('policy') or 'policy'})"
    if type_ is NotificationType.AUTOMATION:
        # The rule already rendered its own message; the rule NAME is the
        # fallback, because a rule with an empty template is still worth seeing.
        return str(payload.get("message") or f'Rule "{payload.get("rule") or "?"}" fired')
    if type_ is NotificationType.APPROVAL:
        target = payload.get("to_state") or "?"
        action = payload.get("action")
        if action == "approved":
            return f"{actor} approved the move to {target}"
        if action == "declined":
            return f"{actor} declined the move to {target}"
        return f"{actor} requested your approval to move to {target}"
    if type_ is NotificationType.PAGE_UPDATED:
        # The page's title is the line's SUBJECT (and its link), so naming it
        # here too would print it twice — `_entry` (RADD-719).
        return f"{actor} edited the page"
    # A type added without a line lands here NAMED, rather than silently reading
    # as whichever branch happened to be last.
    return f"{actor}: {type_.value.replace('_', ' ')}"


def _entry(notification: Notification, actor_names: dict[uuid.UUID, str]) -> mailrender.DigestEntry:
    payload = notification.payload or {}
    type_ = NotificationType(notification.type)
    actor = (
        actor_names.get(notification.actor_id)
        or payload.get("actor_name")
        or UNKNOWN_ACTOR
    )
    headline = _headline(type_, actor, payload)
    base = settings.app_base_url
    if type_ is NotificationType.PAGE_UPDATED:
        space, page = payload.get("space_slug"), payload.get("page_slug")
        return mailrender.DigestEntry(
            headline=headline,
            subject=payload.get("title") or "",
            url=mailrender.page_url(base, space, page) if space and page else "",
        )
    key = payload.get("item_key") or ""
    title = payload.get("item_title") or ""
    return mailrender.DigestEntry(
        headline=headline,
        # Automation notifications carry neither (their payload is message+rule),
        # so the line degrades to the message with no link rather than to a
        # `/issues/` URL with nothing after it.
        subject=f"[{key}] {title}".strip() if key else "",
        excerpt=payload.get("excerpt") or "",
        url=mailrender.issue_url(base, key) if key else "",
    )


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
    which is what makes "nine types, nine lines" testable."""
    return mailrender.digest(
        [_entry(notification, actor_names) for notification in notifications],
        inbox=mailrender.inbox_url(settings.app_base_url),
    )


async def run_once() -> int:
    """Send one digest per user with pending (unemailed, unread, recent) notifications.
    Already-read or too-old rows are stamped without sending so the backlog drains."""
    if not settings.smtp_host:
        return 0
    now = utcnow()
    cutoff = now - timedelta(hours=settings.notify_email_max_age_hours)
    sent = 0
    async with SessionLocal() as session:
        result = await session.execute(
            select(Notification)
            .where(Notification.emailed_at.is_(None))
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
            # Opted-out users still get their rows stamped below (the backlog drains).
            if user_id not in digest_off and user is not None and user.active and user.email and pending:
                message = compose(pending, actor_names)
                try:
                    await asyncio.to_thread(
                        _send_digest, user.email, user.name, message, len(pending)
                    )
                    sent += 1
                except Exception:
                    logger.exception("notify: digest send to %s failed", user.email)
                    continue  # leave rows unstamped — retried next interval
            await session.execute(
                update(Notification)
                .where(Notification.id.in_([n.id for n in notifications]))
                .values(emailed_at=now)
            )
        await session.commit()
    return sent
