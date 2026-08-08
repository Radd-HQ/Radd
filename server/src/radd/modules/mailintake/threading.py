"""Matching an inbound message to its issue, and recording what we sent (RADD-952/954).

**The order is the design.**

    1. In-Reply-To          what a mail client sets when a human hits Reply
    2. References, newest first   the chain, which survives a client that drops (1)
    3. Subject key [RADD-812]     last resort — a human can type it
    4. nothing                    a new issue

Steps 1 and 2 resolve against `mail_messages`, so they only work if every
outbound id was stored. That is the easiest step in the whole feature to forget,
because nothing fails until a reply arrives days later, at a customer.

**Sub-addressing is deliberately absent.** `help+<token>@` is the obvious
mechanism and it breaks in exactly the environments this feature targets:
corporate mail systems and mailing lists rewrite or strip `+` addressing, and a
Google Workspace admin can disable it outright. `parsing.extract_project_key`
still reads a plus tag, but for ROUTING a first contact to a project — a
different question, and one that fails safe.

Candidate extraction is pure and lives beside the lookup so it can be tested on
fixture bytes: real clients emit `References` as whitespace- or comma-separated,
folded across lines, and sometimes with junk between the angle brackets.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow

from .models import MailMessage
from .types import DEDUP_WINDOW, MailDirection

#: An angle-bracketed message id. Anything outside the brackets is noise a
#: client added (comments, whitespace, stray commas) and is skipped.
MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")


def parse_message_ids(value: str | None) -> list[str]:
    """Every `<id>` in a header value, in order, deduped.

    Order is preserved because `References` is chronological: the LAST entry is
    the message being replied to, which is why the caller reverses it.
    """
    if not value:
        return []
    seen: dict[str, None] = {}
    for match in MESSAGE_ID_RE.finditer(value):
        seen.setdefault(match.group(0), None)
    return list(seen)


def thread_candidates(in_reply_to: str | None, references: str | None) -> list[str]:
    """The ids to try, in priority order.

    `In-Reply-To` first — it names the direct parent. Then `References` REVERSED,
    because the chain runs oldest → newest and the newest ancestor is the most
    specific answer: a long-running thread whose early messages were about a
    different issue must resolve to the recent one.
    """
    candidates = parse_message_ids(in_reply_to)
    for message_id in reversed(parse_message_ids(references)):
        if message_id not in candidates:
            candidates.append(message_id)
    return candidates


async def item_for_message_ids(
    session: AsyncSession, message_ids: list[str]
) -> uuid.UUID | None:
    """The first candidate that names a message Radd sent. One query, then the
    caller's own ordering applied in Python — a query per candidate would be a
    round trip per hop of a long References chain."""
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
    """Has this exact inbound id already been accepted inside the window?

    The authoritative answer is the unique index — this is the cheap pre-check
    that turns the common retry into a `200` without provoking an integrity
    error. `record()` still has to handle the race.
    """
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
    """Store one message id against its item.

    Returns None when the id is already stored — the concurrent-retry case. The
    caller reads that as "duplicate", which is the same answer `is_duplicate`
    would have given had it won the race.

    `source_id` is the mail source the message ARRIVED at, and only an INBOUND
    caller has one to pass (RADD-979): `intake.accept` knows its source, while
    an outbound row is the answer to a question this column asks. It is what
    `origin_source_id` reads back to decide which identity replies leave under.
    """
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
    """Which mail source this item's conversation ARRIVED at (RADD-979), or None.

    **The EARLIEST inbound row that names one**, not the latest. A thread often
    gains addresses — someone CCs `sales@` on message four, and that message is
    recorded against its own source too. Taking the newest would hand the
    conversation's identity to whichever mailbox happened to be copied last,
    changing the From address mid-conversation for the one person who never
    asked for it.

    None is the common answer: an item raised in the UI has no mail origin at
    all, and an instance that never bound a sender never reads the result. One
    lookup on the `(item_id, created_at)` index, so asking per outbound message
    costs the same as asking once.
    """
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
    """The item's message ids oldest-first — the `References` header of the next
    outbound message.

    Capped because `References` is a header, not an archive: clients thread on
    the first and last few entries and some relays truncate long ones anyway.
    Keeping the OLDEST (the thread root, which every client anchors on) plus the
    most recent is what the cap has to preserve, so it takes from both ends.
    """
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
    """The subject this thread started with. Byte-stable for its whole life —
    re-deriving it from the item title means renaming an issue silently splits
    the conversation in every participant's client."""
    return await session.scalar(
        select(MailMessage.subject)
        .where(MailMessage.item_id == item_id, MailMessage.subject != "")
        .order_by(MailMessage.created_at)
        .limit(1)
    )
