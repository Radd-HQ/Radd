"""Matching an inbound message to its issue, and recording what we sent (RADD-952/954).

    1. In-Reply-To                what a client sets when a human hits Reply
    2. References, newest first   survives a client that drops (1)
    3. Subject key [RADD-812]     last resort — a human can type it
    4. nothing                    a new issue

1 and 2 resolve against `mail_messages`, so every OUTBOUND id must be stored —
nothing fails until a reply arrives days later. Sub-addressing (`help+token@`)
is deliberately not a threading mechanism: corporate relays strip it.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow

from .models import MailMessage
from .types import DEDUP_WINDOW, MailDirection

#: An angle-bracketed message id; anything outside the brackets is client noise.
MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")


def parse_message_ids(value: str | None) -> list[str]:
    """Every `<id>` in a header value, in order (`References` is chronological), deduped."""
    if not value:
        return []
    seen: dict[str, None] = {}
    for match in MESSAGE_ID_RE.finditer(value):
        seen.setdefault(match.group(0), None)
    return list(seen)


def thread_candidates(in_reply_to: str | None, references: str | None) -> list[str]:
    """The ids to try, in priority order: `In-Reply-To`, then `References` REVERSED —
    the newest ancestor is the most specific answer."""
    candidates = parse_message_ids(in_reply_to)
    for message_id in reversed(parse_message_ids(references)):
        if message_id not in candidates:
            candidates.append(message_id)
    return candidates


async def item_for_message_ids(
    session: AsyncSession, message_ids: list[str]
) -> uuid.UUID | None:
    """The first candidate that names a message Radd sent — one query, the caller's
    ordering applied in Python."""
    if not message_ids:
        return None
    rows = await session.execute(
        select(MailMessage.message_id, MailMessage.item_id).where(
            MailMessage.message_id.in_(message_ids)
        )
    )
    found = dict(rows.all())
    for message_id in message_ids:
        if message_id in found:
            return found[message_id]
    return None


async def is_duplicate(session: AsyncSession, message_id: str) -> bool:
    """Has this inbound id been accepted inside the window? A cheap pre-check; the
    unique index is authoritative and `record()` handles the race."""
    if not message_id:
        return False  # no id = nothing to dedup on; better a duplicate than a drop
    row = await session.scalar(
        select(MailMessage.created_at).where(MailMessage.message_id == message_id)
    )
    return row is not None and row >= utcnow() - DEDUP_WINDOW


async def record(
    session: AsyncSession,
    *,
    message_id: str,
    item_id: uuid.UUID,
    direction: MailDirection,
    subject: str = "",
    comment_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
) -> MailMessage | None:
    """Store one message id against its item; None when it is already stored (the
    concurrent-retry case, read as "duplicate"). `source_id` is INBOUND-only
    (RADD-979), read back by `origin_source_id`."""
    if not message_id:
        return None
    existing = await session.scalar(
        select(MailMessage).where(MailMessage.message_id == message_id)
    )
    if existing is not None:
        return None
    row = MailMessage(
        message_id=message_id,
        item_id=item_id,
        comment_id=comment_id,
        direction=direction.value,
        subject=subject[:998],
        source_id=source_id,
    )
    session.add(row)
    await session.flush()
    return row


async def origin_source_id(session: AsyncSession, item_id: uuid.UUID) -> uuid.UUID | None:
    """The EARLIEST inbound row naming a source (RADD-979) — a mailbox CC'd later
    must not take over the conversation's identity. None for UI-born items."""
    return await session.scalar(
        select(MailMessage.source_id)
        .where(
            MailMessage.item_id == item_id,
            MailMessage.direction == MailDirection.INBOUND.value,
            MailMessage.source_id.is_not(None),
        )
        .order_by(MailMessage.created_at)
        .limit(1)
    )


async def thread_chain(session: AsyncSession, item_id: uuid.UUID, limit: int = 20) -> list[str]:
    """The item's message ids oldest-first — the next outbound `References`. Capped
    from BOTH ends: clients anchor on the root and thread on the most recent."""
    rows = await session.execute(
        select(MailMessage.message_id)
        .where(MailMessage.item_id == item_id)
        .order_by(MailMessage.created_at)
    )
    chain = list(rows.scalars())
    if len(chain) <= limit:
        return chain
    keep_head = limit // 2
    return chain[:keep_head] + chain[-(limit - keep_head) :]


async def thread_subject(session: AsyncSession, item_id: uuid.UUID) -> str | None:
    """The subject this thread started with — byte-stable, so a title edit cannot
    split the conversation."""
    return await session.scalar(
        select(MailMessage.subject)
        .where(MailMessage.item_id == item_id, MailMessage.subject != "")
        .order_by(MailMessage.created_at)
        .limit(1)
    )
