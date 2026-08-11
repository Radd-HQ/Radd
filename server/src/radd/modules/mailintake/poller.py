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
    # Resolved, not raw (RADD-969): a Gmail/Outlook row stores no host, port or
    # username — its kind's preset answers them, and the poll is otherwise the
    # same poll.
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
    """Poll every configured mailbox. Returns the messages processed.

    **The zero-source early return IS the poller's gate (RADD-970).** The loop
    itself only asks whether this process runs workers; whether there is
    anything to poll is a question about ROWS, and `PeriodicLoop.enabled` is
    sync and cannot ask the database. So it is asked here, once a tick, and an
    instance with no mailboxes pays one indexed SELECT a minute for the property
    that an admin adding one in Settings → Email needs no restart.
    """
    async with SessionLocal() as session:
        sources = await registry.polled_sources(session)
        if not sources:
            return 0
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
        except Exception:
            # A poison message. Before RADD-1035 it was flagged `\\Seen` and
            # forgotten with only a log line — a silent loss. Now the drop is on
            # the queryable event stream, THEN the message is flagged so the poll
            # does not wedge on it. Unlike the webhook, there is nobody to 5xx.
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
                    # IMAP exposes no envelope sender, so the rate limiter is
                    # keyed on the FROM HEADER here — forgeable, acceptable for
                    # a circuit breaker, and not acceptable for anything that
                    # granted access.
                    envelope_from=plan.sender_email,
                    source_id=source.id,
                    default_project_id=default_project_id,
                )
                await session.commit()
            # Post-commit: never ack a rolled-back item — and, since RADD-970,
            # also what puts the inbound Message-ID in the store before the ack
            # reads it back out as In-Reply-To.
            if outcome.ack is not None:
                await service.send_ack(
                    item_id=outcome.ack.item_id,
                    email=outcome.ack.email,
                    name=outcome.ack.name,
                    item_key=outcome.ack.item_key,
                    title=outcome.ack.title,
                )
        except Exception:
            # Flagged `\\Seen` anyway below — a poison message must not wedge
            # the poll. Unlike the webhook, there is nobody to hand a 5xx to.
            logger.exception("mailintake: intake failed for uid=%s on %s", uid, source.name)
        processed.append(uid)
    await asyncio.to_thread(mark_seen, source, processed)
    return len(processed)


async def _emit_dropped(source: MailSource, *, reason: str) -> None:
    """Record a poller-side loss on the event stream (RADD-1035).

    A message the poller cannot even parse never reaches `intake`, so it would
    otherwise be flagged Seen and forgotten with nothing queryable saying so.
    The `entity_id` is a fresh uuid4 — an unparseable message has no Message-ID
    to correlate on, which is exactly what makes it unparseable — and the SOURCE
    is on the payload, so an operator can still see WHICH mailbox is dropping mail
    and how often. Its own failure is swallowed: this is the error path, and it
    must not raise back into a poll it is trying to keep honest.
    """
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
