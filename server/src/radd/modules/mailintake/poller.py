"""IMAP poll + intake (specs 47+62). The blocking imaplib calls run in a worker
thread (asyncio.to_thread); the item/comment writes run on the event loop
through the items/comments seams as the SYSTEM actor. \\Seen is the cursor:
messages are fetched with BODY.PEEK and flagged only after an intake attempt
(a poison message is logged and still flagged — no retry loop).

Spec 62 additions: senders matching no active user become the item's
mail_contact (reporter stays NULL), threaded replies refresh the contact's
last_message_id, plus-addressed recipients (`support+td@…`) route to that
project, and a created-with-contact item is acknowledged by email AFTER the
transaction commits."""

import asyncio
import imaplib
import logging

from radd.config import settings
from radd.db import SessionLocal

from . import intake, parsing, service
from .types import SEEN_FLAG

logger = logging.getLogger(__name__)


# --- blocking IMAP side (runs via asyncio.to_thread) ---


def _connect() -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(settings.mail_imap_host, settings.mail_imap_port)
    imap.login(settings.mail_imap_username, settings.mail_imap_password)
    imap.select(settings.mail_imap_folder)
    return imap


def fetch_unseen() -> list[tuple[str, bytes]]:
    """(uid, raw message bytes) for every UNSEEN message. BODY.PEEK leaves the
    \\Seen cursor untouched until the intake attempt completes; UIDs are stable
    across connections (unlike sequence numbers)."""
    with _connect() as imap:
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


def mark_seen(uids: list[str]) -> None:
    with _connect() as imap:
        for uid in uids:
            imap.uid("STORE", uid, "+FLAGS", SEEN_FLAG)


# --- async intake side ---


async def run_once() -> int:
    """Fetch, take in, flag.

    RADD-951: the per-message decisions are NOT here. Parsing, dedup, threading,
    quote stripping, attachments and the loop guards all live in `intake`, and
    this poller is now one of two callers of it — the webhook source is the
    other. That is what makes the MailSource seam real rather than notional: a
    Gmail adapter is a third caller, not a third copy.
    """
    messages = await asyncio.to_thread(fetch_unseen)
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
                    default_project_key=settings.mail_project_key,
                    own_addresses=own_addresses(),
                    envelope_from=plan.sender_email,
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
            # Flagged \\Seen anyway below — a poison message must not wedge the
            # poll. Unlike the webhook, there is nobody to hand a 5xx to.
            logger.exception("mailintake: intake failed for message uid=%s (skipped)", uid)
        processed.append(uid)
    await asyncio.to_thread(mark_seen, processed)
    return len(processed)


def own_addresses() -> set[str]:
    """Every address Radd sends AS — the self-loop guard's comparison set."""
    from email.utils import parseaddr

    found = {parseaddr(settings.smtp_from_address)[1].lower()}
    if settings.mail_imap_username:
        found.add(settings.mail_imap_username.lower())
    return {address for address in found if address}
