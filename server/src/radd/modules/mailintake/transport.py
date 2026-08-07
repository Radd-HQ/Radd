"""The one way anything mails a person ABOUT AN ISSUE (RADD-968).

There used to be two fan-outs. The outbound consumer mailed notify's watcher set
on `comment.created`; the INBOX fanned out over watchers ∪ participant-team
members through notify's permission-gated consumer. So a team participant got an
inbox row and no email, a watcher who had since lost `item.read` still got mail,
a muted type was muted in-app only, and no event but `comment.created` ever
mailed anyone at all.

Notify now decides WHO hears — it already did, for the inbox — and this file
carries the message: the sender ROW (or the environment relay), threading
headers off the message store, the id the provider actually used, and the
`mail.sent`/`mail.failed` events. `mailintake.service` re-exports it, because
this is a public seam and `service.py` is where other modules look.

That split is what makes notification mail a conversation rather than a
broadcast: it threads on the item, carries the sender's Reply-To, and a reply
lands back on the same issue through intake.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.events import service as events

from . import registry, senders, threading
from .providers import OutboundMessage
from .types import MailDirection, MailEntity, MailEvent, MailSenderKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EnvSender:
    """The environment relay wearing a `mail_senders` row's shape.

    A seed-era instance has no sender row — `seeding.seed_from_env` only writes
    one when `RADD_SMTP_HOST` is set at first boot, and an instance that gained
    SMTP later has none at all. `send_ack` has always had this fallback; without
    it here, upgrading would SILENTLY stop every notification email on exactly
    those instances. A frozen dataclass rather than a detached `MailSender`, so
    nothing can flush a synthetic row into the table.

    It carries a `kind` because RADD-969 made every connection detail resolve
    against the kind's preset (`resolve.py`), and an env relay IS the custom
    `smtp` kind: a named host from the environment is by definition not Gmail's.
    Stating that here is cheaper than teaching `resolve` and `SmtpSender` to
    tolerate a kindless duck — that would put a branch in every one of the six
    resolvers to serve one caller.
    """

    host: str
    port: int
    username: str
    secret: str
    starttls: bool
    from_address: str
    reply_to: str
    kind: str = MailSenderKind.SMTP.value


def _env_sender() -> _EnvSender | None:
    if not settings.smtp_host:
        return None
    return _EnvSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        secret=settings.smtp_password,
        starttls=settings.smtp_starttls,
        from_address=settings.smtp_from_address,
        reply_to=settings.email_ingest_address,
    )


async def _sender(session: AsyncSession):
    """The configured sender, built from its ROW (RADD-958), else the env relay.

    Returns `(sender, row)` or `(None, None)`. The kind→implementation map is
    `senders.sender_for` and lives nowhere else (RADD-969) — this file and the
    settings test-send both call it, so a Gmail sender row that the transport
    happily uses cannot be one the test button calls unimplemented. It is also
    what makes a Gmail adapter a class plus a row rather than an edit here.
    """
    row = await registry.default_sender(session) or _env_sender()
    if row is None:
        return None, None
    sender = senders.sender_for(row)
    if sender is None:
        logger.warning("mailintake: no sender implementation for kind %r", row.kind)
        return None, None
    return sender, row


async def outbound_configured(session: AsyncSession) -> bool:
    """Is there anywhere to send FROM at all? A caller with a loop to run asks
    once per tick rather than discovering it per recipient."""
    sender, _ = await _sender(session)
    return sender is not None


@asynccontextmanager
async def _session(session: AsyncSession | None):
    """The caller's session, or one of our own that we commit.

    Both callers exist. Notify's mailer and the outbound consumer send
    post-commit with nothing left to join, so they pass nothing; a test (and any
    future in-transaction caller) passes its session and owns the commit — which
    is also the only way the seam can be exercised against rows that were never
    committed.
    """
    if session is not None:
        yield session
        return
    async with SessionLocal() as own:
        yield own
        await own.commit()


async def _thread_headers(
    session: AsyncSession, item_id: uuid.UUID, *, row, subject: str
) -> tuple[dict[str, str], str]:
    """Headers + the subject that keeps this item's thread ONE conversation.

    The stored subject wins, byte-stable for the thread's whole life: re-deriving
    it from the item title means renaming an issue silently splits the
    conversation in every participant's client. `subject` is only the opening
    line, for an item that has never been mailed about.
    """
    stored = await threading.thread_subject(session, item_id)
    if stored:
        subject = stored if stored.lower().startswith("re:") else f"Re: {stored}"
    # Plain `help@`, no token: sub-addressing is stripped or rewritten by exactly
    # the corporate systems this feature targets (RADD-954).
    headers = {"Reply-To": row.reply_to or row.from_address}
    chain = await threading.thread_chain(session, item_id)
    if chain:
        headers["In-Reply-To"] = chain[-1]
        headers["References"] = " ".join(chain)
    return headers, subject


async def send_item_mail(
    session: AsyncSession | None = None,
    *,
    item_id: uuid.UUID,
    to_address: str,
    to_name: str = "",
    subject: str,
    text: str,
    html: str = "",
    comment_id: uuid.UUID | None = None,
) -> str | None:
    """Mail one person about one issue. Returns the Message-ID that went on the
    wire, or None when nothing was sent (no relay, no address, a failure).

    `subject` is the OPENING subject — `[KEY] Title` — used only while the item
    has no mail thread; after that the stored one wins, prefixed `Re: `.

    Never raises: a caller mailing a list must not lose the rest of it to one
    unreachable address, and a reply is not worth a retry queue. The failure is
    logged AND emitted as `mail.failed` against the item, because "the customer
    never got it" being only a log line is what made it invisible to every
    screen and every rule (RADD-960).

    The recorded id is the one the SENDER REPORTS (`MailSender.send`'s return
    value), not the one composed: SMTP honours a client-set id and the Gmail API
    replaces it, and storing an intended value the provider did not use makes
    every reply arrive unthreaded — days later, at a customer, with nothing
    raised anywhere.
    """
    if not to_address:
        return None
    async with _session(session) as db:
        sender, row = await _sender(db)
        if sender is None:
            return None
        headers, subject = await _thread_headers(db, item_id, row=row, subject=subject)
        try:
            sent = await sender.send(
                OutboundMessage(
                    to_address=to_address,
                    to_name=to_name,
                    subject=subject,
                    body=text,
                    html_body=html,
                    headers=headers,
                )
            )
        except Exception:
            logger.exception(
                "mailintake: mail to %s about %s failed (dropped)", to_address, item_id
            )
            await _emit_outcome(db, item_id, MailEvent.FAILED, to_address, subject)
            return None
        if sent:
            await threading.record(
                db,
                message_id=sent,
                item_id=item_id,
                direction=MailDirection.OUTBOUND,
                subject=subject,
                comment_id=comment_id,
            )
        await _emit_outcome(db, item_id, MailEvent.SENT, to_address, subject)
        return sent


async def _emit_outcome(
    session: AsyncSession,
    item_id: uuid.UUID,
    event_type: MailEvent,
    address: str,
    subject: str,
) -> None:
    """Report what the channel did (RADD-960). Item-scoped, so a rule can flag
    the ticket — the whole point of emitting rather than logging harder.

    One event per MESSAGE (it was one per fan-out batch), because a fan-out is
    now several independent sends that can succeed and fail separately. The
    payload keeps its shape — `recipients` is a one-element list — so no rule
    written against `mail.sent` has to change.
    """
    await events.emit(
        session,
        event_type=event_type,
        entity_type=MailEntity.MAIL,
        entity_id=item_id,
        subjects={"item": item_id},
        payload={
            "recipients": [address],
            "recipient_count": 1,
            "subject": subject,
            # No body, for the reason in intake._mail_facts.
        },
    )
