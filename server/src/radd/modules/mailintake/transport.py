"""The one way anything mails a person (RADD-968/983).

Notify decides WHO hears; this file carries the message: the sender (resolved
per item — `_sender`), threading headers from the message store, the Message-ID
the provider actually used, and the `mail.sent`/`mail.failed` events.
`send_item_mail` threads on an issue so a reply lands back on it;
`send_plain_mail` is the same delivery with no conversation (a digest, an
automation mail at set arity). Both share `_deliver`: never raise, record the
sender's id, emit the outcome. `mailintake.service` re-exports the public seam.
"""

from __future__ import annotations

from collections.abc import Mapping

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.mailtypes import MailAttachment
from radd.db import SessionLocal
from radd.modules.events import service as events

from radd.clock import utcnow

# RADD-1385: the failure vocabulary is notify's (its retry ladder).
from radd.modules.notify.transport import MailFailureReport

from . import registry, senders, threading
from .providers import OutboundMessage
from .types import (
    MAIL_ERROR_MAX_CHARS,
    MAIL_HEALTH_SCAN_LIMIT,
    MAIL_HEALTH_WINDOW_HOURS,
    MailDirection,
    MailEntity,
    MailEvent,
    MailSenderKind,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EnvSender:
    """The env relay wearing a `mail_senders` row's shape — for an instance with
    no sender row (seeded only when `RADD_SMTP_HOST` was set at first boot).
    Frozen so it can never be flushed into the table; `kind` is SMTP because an
    env-named host is by definition the custom kind (RADD-969).
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


async def _origin_sender(session: AsyncSession, item_id: uuid.UUID):
    """The sender bound to the source this item's mail ARRIVED at, or None."""
    source_id = await threading.origin_source_id(session, item_id)
    if source_id is None:
        return None
    return await registry.bound_sender(session, source_id)


async def _sender(session: AsyncSession, item_id: uuid.UUID | None = None):
    """The sender for an item, else the default row, else the env relay.

    Per ITEM first (RADD-979): the sender bound to the source the conversation
    ARRIVED at, so a ticket raised at `help@` is answered from `help@`. This is
    the one resolution point — replies, receipts and notify's mail all ride it.
    Returns `(sender, row)` or `(None, None)`; the kind→implementation map is
    `senders.sender_for`, shared with the settings test-send (RADD-969).
    """
    row = await _origin_sender(session, item_id) if item_id is not None else None
    row = row or await registry.default_sender(session) or _env_sender()
    if row is None:
        return None, None
    sender = senders.sender_for(row)
    if sender is None:
        logger.warning("mailintake: no sender implementation for kind %r", row.kind)
        return None, None
    return sender, row


async def outbound_configured(session: AsyncSession) -> bool:
    """Is there anywhere to send FROM at all? Item-independent (it gates a loop):
    the default sender, else any source-bound one — relays each bound to a source
    leave no default (`default_sender` will not guess between two)."""
    sender, _ = await _sender(session)
    if sender is not None:
        return True
    return await registry.any_bound_sender(session)


@asynccontextmanager
async def _session(session: AsyncSession | None):
    """The caller's session (a test; it owns the commit), or one of our own that we
    commit (the post-commit senders)."""
    if session is not None:
        yield session
        return
    async with SessionLocal() as own:
        yield own
        await own.commit()


async def _thread_headers(
    session: AsyncSession, item_id: uuid.UUID, *, row, subject: str, pin_subject: bool = False
) -> tuple[dict[str, str], str]:
    """Headers + the subject that keeps this item's thread ONE conversation. The
    stored subject wins (a title edit must not split the thread); `pin_subject`
    overrides the subject only — the threading headers come from the store."""
    if not pin_subject:
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
    pin_subject: bool = False,
    attachments: tuple[MailAttachment, ...] = (),
    failure: MailFailureReport = MailFailureReport.REPORT,
    headers: Mapping[str, str] | None = None,
    kind: StrEnum,
) -> str | None:
    """Mail one person about one issue. Returns the Message-ID that went on the
    wire, or None when nothing was sent. Never raises: a failure is logged and
    emitted as `mail.failed` against the item (RADD-960).

    `subject` is the OPENING subject, used only until the item has a thread;
    after that the stored one wins, prefixed `Re: `. `pin_subject=True` sends
    `subject` verbatim — for messages that open their own topic (the receipt,
    whose bracketed key is the subject-line threading fallback; the resolution
    notice, the CSAT survey, automation mail). Threading headers always come from
    the store, and caller `headers` (e.g. `List-Unsubscribe`) never override them.
    `failure` is the caller's retry policy (`MailFailureReport`); only notify's
    loops pass it.
    """
    if not to_address:
        return None
    async with _session(session) as db:
        # Per ITEM (RADD-979): the address the conversation arrived at.
        sender, row = await _sender(db, item_id)
        if sender is None:
            return None
        thread_headers, subject = await _thread_headers(
            db, item_id, row=row, subject=subject, pin_subject=pin_subject
        )
        return await _deliver(
            db,
            sender=sender,
            item_id=item_id,
            to_address=to_address,
            to_name=to_name,
            subject=subject,
            text=text,
            html=html,
            headers={**(headers or {}), **thread_headers},
            comment_id=comment_id,
            failure=failure,
            attachments=attachments,
            kind=kind,
        )


async def send_plain_mail(
    session: AsyncSession | None = None,
    *,
    to_address: str,
    to_name: str = "",
    subject: str,
    text: str,
    html: str = "",
    failure: MailFailureReport = MailFailureReport.REPORT,
    headers: Mapping[str, str] | None = None,
    kind: StrEnum,
) -> str | None:
    """Mail one person about NO issue (RADD-983). Returns the Message-ID, or
    None when nothing was sent; never raises.

    No thread, no stored subject, nothing recorded in the message store, and
    no Reply-To — pointing a digest's Reply-To at the intake address would turn
    a reply into a new ticket. Events carry no item subject, like
    `mail.dropped`. `headers` go on the wire as given.
    """
    if not to_address:
        return None
    async with _session(session) as db:
        sender, _row = await _sender(db)
        if sender is None:
            return None
        return await _deliver(
            db,
            sender=sender,
            item_id=None,
            to_address=to_address,
            to_name=to_name,
            subject=subject,
            text=text,
            html=html,
            headers=dict(headers or {}),
            comment_id=None,
            failure=failure,
            kind=kind,
        )


async def _deliver(
    session: AsyncSession,
    *,
    sender,
    item_id: uuid.UUID | None,
    to_address: str,
    to_name: str,
    subject: str,
    text: str,
    html: str,
    headers: dict[str, str],
    comment_id: uuid.UUID | None,
    failure: MailFailureReport,
    kind: StrEnum,
    attachments: tuple[MailAttachment, ...] = (),
) -> str | None:
    """One message onto one relay, and the report of what happened to it. The
    recorded id is the SENDER's return value, not the composed one (the Gmail API
    replaces it; storing the intended id leaves every reply unthreaded)."""
    try:
        sent = await sender.send(
            OutboundMessage(
                to_address=to_address,
                to_name=to_name,
                subject=subject,
                body=text,
                html_body=html,
                headers=headers,
                attachments=attachments,
            )
        )
    except Exception as exc:
        logger.exception(
            "mailintake: mail to %s about %s failed (dropped)", to_address, item_id or "—"
        )
        if failure is not MailFailureReport.SILENT:
            await _emit_outcome(
                session,
                item_id,
                MailEvent.FAILED,
                to_address,
                subject,
                kind=kind,
                error=_error_text(exc),
                given_up=failure is MailFailureReport.TERMINAL,
            )
        return None
    if sent and item_id is not None:
        await threading.record(
            session,
            message_id=sent,
            item_id=item_id,
            direction=MailDirection.OUTBOUND,
            subject=subject,
            comment_id=comment_id,
        )
    await _emit_outcome(session, item_id, MailEvent.SENT, to_address, subject, kind=kind)
    return sent


def _error_text(exc: BaseException) -> str:
    """What went wrong, in one line (RADD-1036). The class name stays because
    some carry no message (`SMTPServerDisconnected()` stringifies to "")."""
    return f"{type(exc).__name__}: {exc}".strip()[:MAIL_ERROR_MAX_CHARS]


async def _emit_outcome(
    session: AsyncSession,
    item_id: uuid.UUID | None,
    event_type: MailEvent,
    address: str,
    subject: str,
    *,
    kind: StrEnum,
    error: str = "",
    given_up: bool = False,
) -> None:
    """Emit `mail.sent`/`mail.failed` (RADD-960): item-scoped when there is an
    item so a rule can act on the ticket; otherwise a synthetic entity id and no
    subject, like `mail.dropped`. One event per message; `error` and `given_up`
    ride failures only (RADD-1036).
    """
    payload: dict[str, object] = {
        "recipients": [address],
        "recipient_count": 1,
        "subject": subject,
        # RADD-1318: what this mail WAS — a reply, a digest, an automation's.
        "kind": kind.value,
        # No body, for the reason in intake._mail_facts.
    }
    if event_type is MailEvent.FAILED:
        payload["error"] = error
        payload["given_up"] = given_up
    await events.emit(
        session,
        event_type=event_type,
        entity_type=MailEntity.MAIL,
        # Synthetic for an itemless mail: `entity_id` is the events table's address.
        entity_id=item_id or uuid.uuid4(),
        subjects={"item": item_id} if item_id is not None else None,
        payload=payload,
    )


# --- mail health (RADD-1036) --------------------------------------------------


@dataclass(frozen=True)
class MailFailure:
    """One failed message, as an operator reads it."""

    at: datetime
    recipient: str
    subject: str
    error: str
    #: The retry ladder ran out on this one — nobody is going to hear from us.
    given_up: bool


@dataclass(frozen=True)
class MailHealth:
    """Outbound failures over the last `window_hours` (RADD-1036). Aggregated here,
    beside `_emit_outcome`, because the payload shape is this file's; Monitoring
    reads it through the public seam."""

    window_hours: int
    failures: int
    given_up: int
    #: True when `failures` hit `MAIL_HEALTH_SCAN_LIMIT` — the count is a floor.
    capped: bool
    recent: tuple[MailFailure, ...]


async def mail_health(
    session: AsyncSession,
    *,
    window_hours: int = MAIL_HEALTH_WINDOW_HOURS,
    recent: int = 5,
) -> MailHealth:
    """Outbound failures in the recent past, newest first (via `events.query_events`)."""
    rows = await events.query_events(
        session,
        event_types=[MailEvent.FAILED.value],
        start=utcnow() - timedelta(hours=window_hours),
        limit=MAIL_HEALTH_SCAN_LIMIT,
    )
    failures = tuple(_failure(row) for row in rows)
    return MailHealth(
        window_hours=window_hours,
        failures=len(failures),
        given_up=sum(1 for failure in failures if failure.given_up),
        capped=len(failures) >= MAIL_HEALTH_SCAN_LIMIT,
        recent=failures[:recent],
    )


def _failure(event) -> MailFailure:
    payload = event.payload or {}
    recipients = payload.get("recipients") or []
    return MailFailure(
        at=event.created_at,
        recipient=str(recipients[0]) if recipients else "",
        subject=str(payload.get("subject") or ""),
        # Rows from before RADD-1036 carry no `error` key.
        error=str(payload.get("error") or ""),
        given_up=bool(payload.get("given_up")),
    )
