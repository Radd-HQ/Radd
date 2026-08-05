"""Email digests: one plain-text email per user batching their unemailed
notifications. Sends through the shared radd.smtp helper in a thread — no new
dependency; an empty RADD_SMTP_HOST (the default) disables the loop entirely."""

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select, update

from radd import smtp
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth

from . import service
from .models import Notification
from .types import NotificationType
from radd.clock import utcnow

logger = logging.getLogger(__name__)



def _line(notification: Notification) -> str:
    payload = notification.payload or {}
    actor = payload.get("actor_name") or "Someone"
    key = payload.get("item_key", "")
    title = payload.get("item_title", "")
    type_ = NotificationType(notification.type)
    if type_ is NotificationType.ASSIGNED:
        verb = f"{actor} assigned you"
    elif type_ is NotificationType.MENTIONED:
        verb = f"{actor} mentioned you"
    elif type_ is NotificationType.STATE_CHANGED:
        verb = f"{actor} moved {payload.get('from')} → {payload.get('to')}"
    else:
        verb = f"{actor} commented"
    lines = [f"• [{key}] {title} — {verb}"]
    if payload.get("excerpt"):
        lines.append(f'  "{payload["excerpt"]}"')
    lines.append(f"  {settings.app_base_url}/issues/{key}")
    return "\n".join(lines)


def _send_digest(to_address: str, to_name: str, body: str, count: int) -> None:
    smtp.send_message(
        to_address,
        f"[Radd] {count} new notification{'s' if count != 1 else ''}",
        body,
        to_name=to_name,
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
        digest_off = await service.digest_disabled_users(session, set(by_user))
        for user_id, notifications in by_user.items():
            user = users.get(user_id)
            pending = [
                n for n in notifications if n.read_at is None and n.created_at >= cutoff
            ]
            # Opted-out users still get their rows stamped below (the backlog drains).
            if user_id not in digest_off and user is not None and user.active and user.email and pending:
                body = "\n\n".join(_line(n) for n in pending)
                body += f"\n\n—\nYour Radd inbox: {settings.app_base_url}/inbox"
                try:
                    await asyncio.to_thread(_send_digest, user.email, user.name, body, len(pending))
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
