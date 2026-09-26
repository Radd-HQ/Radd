"""IMAP poll (specs 47/62; every mailbox is a `mail_sources` row since RADD-958).

Blocking imaplib runs in `asyncio.to_thread`. `\\Seen` is the cursor: messages
are fetched with BODY.PEEK and flagged after the intake attempt, so a poison
message is flagged, not retried forever. Per-message decisions live in `intake`.
"""

import asyncio
import imaplib
import logging
import uuid

from radd.db import SessionLocal
from radd.modules.events import service as events

from . import intake, parsing, registry, resolve, service
from .models import MailSource
from .types import (
    DEFAULT_IMAP_FOLDER,
    POLLER_PARSE_FAILURE_REASON,
    SEEN_FLAG,
    MailEntity,
    MailEvent,
)

logger = logging.getLogger(__name__)


# --- blocking IMAP side (runs via asyncio.to_thread) ---


def _connect(source: MailSource) -> imaplib.IMAP4_SSL:
    # Resolved, not raw (RADD-969): a preset row stores no host, port or username.
    imap = imaplib.IMAP4_SSL(resolve.source_host(source), resolve.source_port(source))
    imap.login(resolve.source_username(source), source.secret)
    imap.select(source.folder or DEFAULT_IMAP_FOLDER)
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
    """Poll every configured mailbox; returns the messages processed. The
    zero-source early return IS the poller's gate (RADD-970): `PeriodicLoop.enabled`
    is sync and cannot ask the database, and a new mailbox needs no restart."""
    async with SessionLocal() as session:
        sources = await registry.polled_sources(session)
        if not sources:
            return 0
        own = await registry.own_addresses(session)
        # Detach what the blocking side needs: a lazy load after close would raise.
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
        except Exception:
            # A poison message: emitted as a drop (RADD-1035), then flagged so the
            # poll does not wedge on it.
            logger.warning(
                "mailintake: unparseable message uid=%s on %s", uid, source.name, exc_info=True
            )
            await _emit_dropped(source, reason=POLLER_PARSE_FAILURE_REASON)
            processed.append(uid)
            continue
        try:
            async with SessionLocal() as session:
                outcome = await intake.accept(
                    session,
                    plan,
                    raw=raw,
                    default_project_key="",
                    own_addresses=own,
                    # IMAP has no envelope sender: the rate limiter keys on the
                    # forgeable FROM header — fine for a circuit breaker only.
                    envelope_from=plan.sender_email,
                    source_id=source.id,
                    default_project_id=default_project_id,
                )
                await session.commit()
            # Post-commit: never acknowledge a rolled-back item, and the receipt's
            # In-Reply-To reads the committed inbound id.
            if outcome.ack is not None:
                await service.send_ack(outcome.ack)
        except Exception:
            # Flagged `\\Seen` anyway below — nobody to hand a 5xx to.
            logger.exception("mailintake: intake failed for uid=%s on %s", uid, source.name)
        processed.append(uid)
    await asyncio.to_thread(mark_seen, source, processed)
    return len(processed)


async def _emit_dropped(source: MailSource, *, reason: str) -> None:
    """Record a poller-side loss on the event stream (RADD-1035): a fresh uuid4 (an
    unparseable message has no Message-ID) and the SOURCE on the payload. Never
    raises — this is the error path."""
    try:
        async with SessionLocal() as session:
            await events.emit(
                session,
                event_type=MailEvent.DROPPED,
                entity_type=MailEntity.MAIL,
                entity_id=str(uuid.uuid4()),
                payload={"reason": reason, "source_id": str(source.id)},
            )
            await session.commit()
    except Exception:
        logger.exception("mailintake: could not emit mail.dropped for %s", source.name)
