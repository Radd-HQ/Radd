"""IMAP poll + intake (specs 47+62; row-configured since RADD-958).

The blocking imaplib calls run in a worker thread (`asyncio.to_thread`); the
item/comment writes run on the event loop through the items/comments seams as
the SYSTEM actor. `\\Seen` is the cursor: messages are fetched with BODY.PEEK and
flagged only after an intake attempt, so a poison message is logged and still
flagged — no retry loop.

**Every mailbox is a `mail_sources` row**, not an env var. That is what makes
the routing chain reachable: a message now arrives WITH the source it came from,
so `intake` can walk that source's rules (alias → project, the AI classifier)
instead of falling straight to one instance-wide default. Polling several
mailboxes is now just several rows.

Per-message decisions are NOT here — parsing, dedup, threading, quote stripping,
attachments and the loop guards all live in `intake`, which the webhook source
calls too.
"""

import asyncio
import imaplib
import logging

from radd.db import SessionLocal

from . import intake, parsing, registry, service
from .models import MailSource
from .types import SEEN_FLAG

logger = logging.getLogger(__name__)


# --- blocking IMAP side (runs via asyncio.to_thread) ---


def _connect(source: MailSource) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(source.host, source.port)
    imap.login(source.username, source.secret)
    imap.select(source.folder or "INBOX")
    return imap


def fetch_unseen(source: MailSource) -> list[tuple[str, bytes]]:
    """(uid, raw bytes) for every UNSEEN message. BODY.PEEK leaves the `\\Seen`
    cursor untouched until the intake attempt completes; UIDs are stable across
    connections (unlike sequence numbers)."""
    with _connect(source) as imap:
        status, data = imap.uid("SEARCH", None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return []
        messages: list[tuple[str, bytes]] = []
        for uid in data[0].split():
            status, fetched = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            for part in fetched:
                if isinstance(part, tuple) and part[1]:
                    messages.append((uid.decode(), part[1]))
                    break
        return messages


def mark_seen(source: MailSource, uids: list[str]) -> None:
    with _connect(source) as imap:
        for uid in uids:
            imap.uid("STORE", uid, "+FLAGS", SEEN_FLAG)


# --- async intake side ---


async def run_once() -> int:
    """Poll every configured mailbox. Returns the messages processed."""
    async with SessionLocal() as session:
        sources = await registry.polled_sources(session)
        own = await registry.own_addresses(session)
        # Detach what the blocking side needs: the session closes before the
        # thread runs, and a lazily-loaded attribute there would raise.
        plans = [
            (
                source,
                source.default_project_id,
            )
            for source in sources
        ]
    total = 0
    for source, default_project_id in plans:
        try:
            total += await _drain(source, default_project_id, own)
        except Exception:
            # One unreachable mailbox must not stop the others.
            logger.exception("mailintake: polling %s failed", source.name)
    return total


async def _drain(source: MailSource, default_project_id, own: set[str]) -> int:
    messages = await asyncio.to_thread(fetch_unseen, source)
    if not messages:
        return 0
    processed: list[str] = []
    for uid, raw in messages:
        try:
            plan = parsing.parse_email(raw)
            async with SessionLocal() as session:
                outcome = await intake.accept(
                    session,
                    plan,
                    raw=raw,
                    default_project_key="",
                    own_addresses=own,
                    # IMAP exposes no envelope sender, so the rate limiter is
                    # keyed on the FROM HEADER here — forgeable, acceptable for
                    # a circuit breaker, and not acceptable for anything that
                    # granted access.
                    envelope_from=plan.sender_email,
                    source_id=source.id,
                    default_project_id=default_project_id,
                )
                await session.commit()
            if outcome.ack is not None:  # post-commit: never ack a rolled-back item
                await service.send_ack(
                    email=outcome.ack.email,
                    name=outcome.ack.name,
                    item_key=outcome.ack.item_key,
                    title=outcome.ack.title,
                    message_id=outcome.ack.message_id or None,
                )
        except Exception:
            # Flagged `\\Seen` anyway below — a poison message must not wedge
            # the poll. Unlike the webhook, there is nobody to hand a 5xx to.
            logger.exception("mailintake: intake failed for uid=%s on %s", uid, source.name)
        processed.append(uid)
    await asyncio.to_thread(mark_seen, source, processed)
    return len(processed)
