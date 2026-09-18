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

Since RADD-979 the sender is resolved PER ITEM (see `_sender`), and that it
happens here and nowhere else is the point: three callers inherit the identity
of the address a conversation arrived at without knowing sources exist.

That split is what makes notification mail a conversation rather than a
broadcast: it threads on the item, carries the sender's Reply-To, and a reply
lands back on the same issue through intake.

**Two entry points since RADD-983, and they differ only in whether there is an
item.** `send_item_mail` is above; `send_plain_mail` is the same delivery with
the conversation removed, for the three messages that genuinely have no single
issue behind them — a notification DIGEST spanning ten of them, and an
automation `send_email` addressed to a literal address at set arity. They were
the last senders still dialling `radd.smtp` off the environment, which meant an
instance configured entirely through Settings → Email (sender ROWS, no
`RADD_SMTP_*`) sent them nowhere at all: the guard was `settings.smtp_host`, so
the loop skipped, the cursor advanced, and nothing was logged. Everything that
makes a send observable — the sender resolution, `mail.sent`/`mail.failed`, the
"never raise" contract — is shared, because it lives in `_deliver` and both
entry points are thin wrappers around it.
"""

from __future__ import annotations

from collections.abc import Mapping

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.mailtypes import MailAttachment
from radd.db import SessionLocal
from radd.modules.events import service as events

from radd.clock import utcnow

from . import registry, senders, threading
from .providers import OutboundMessage
from .types import (
    MAIL_ERROR_MAX_CHARS,
    MAIL_HEALTH_SCAN_LIMIT,
    MAIL_HEALTH_WINDOW_HOURS,
    MailDirection,
    MailEntity,
    MailEvent,
    MailFailureReport,
    MailSenderKind,
)

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


async def _origin_sender(session: AsyncSession, item_id: uuid.UUID):
    """The sender bound to the source this item's mail ARRIVED at, or None."""
    source_id = await threading.origin_source_id(session, item_id)
    if source_id is None:
        return None
    return await registry.bound_sender(session, source_id)


async def _sender(session: AsyncSession, item_id: uuid.UUID | None = None):
    """The configured sender, built from its ROW (RADD-958), else the env relay.

    **Resolution order (RADD-979):**

        1. the sender bound to the item's ORIGIN SOURCE   the address it arrived at
        2. the default `mail_senders` row                  the instance's identity
        3. the environment relay                           the seed-era fallback

    Step 1 is the new one, and it is the whole of RADD-979. Which identity
    answers a conversation is a property of the ADDRESS it arrived at, not of
    the instance: a ticket raised at `help@` used to be replied to by `agent@`
    because the sender was one instance-wide choice, so the requester never saw
    the address they had written to on anything Radd sent back.

    **This is the ONE resolution point**, which is why replies, acknowledgements
    and notify's per-event mail all inherit it without knowing it exists — they
    all ride `send_item_mail`. Putting the lookup at any of those three callers
    would have been three copies of it, and the third would have been forgotten.

    Returns `(sender, row)` or `(None, None)`. The kind→implementation map is
    `senders.sender_for` and lives nowhere else (RADD-969) — this file and the
    settings test-send both call it, so a Gmail sender row that the transport
    happily uses cannot be one the test button calls unimplemented. It is also
    what makes a Gmail adapter a class plus a row rather than an edit here.
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
    """Is there anywhere to send FROM at all? A caller with a loop to run asks
    once per tick rather than discovering it per recipient.

    Deliberately item-INDEPENDENT — it gates a loop, which has no item yet — so
    it asks the default question and then, since RADD-979, whether any source
    binds a sender of its own. Both halves are needed: an instance whose relays
    are each bound to one source has no default at all (`default_sender` refuses
    to guess between two enabled rows), and answering False there would silence
    every message that in fact had somewhere to go.
    """
    sender, _ = await _sender(session)
    if sender is not None:
        return True
    return await registry.any_bound_sender(session)


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
    session: AsyncSession, item_id: uuid.UUID, *, row, subject: str, pin_subject: bool = False
) -> tuple[dict[str, str], str]:
    """Headers + the subject that keeps this item's thread ONE conversation.

    The stored subject wins, byte-stable for the thread's whole life: re-deriving
    it from the item title means renaming an issue silently splits the
    conversation in every participant's client. `subject` is only the opening
    line, for an item that has never been mailed about.

    `pin_subject` suppresses that preference — see `send_item_mail`. It touches
    the subject ONLY: the headers a client actually threads on are built from
    the store either way.
    """
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
) -> str | None:
    """Mail one person about one issue. Returns the Message-ID that went on the
    wire, or None when nothing was sent (no relay, no address, a failure).

    `headers` are the CALLER's extra headers (RADD-985: notify's mailer adds
    `List-Unsubscribe` to user-addressed mail). They never override what this
    file computes — Reply-To, In-Reply-To and References are the thread's, and
    a caller that could replace them could split a customer's conversation.

    `subject` is the OPENING subject — `[KEY] Title` — used only while the item
    has no mail thread; after that the stored one wins, prefixed `Re: `.

    **`pin_subject=True` sends `subject` verbatim instead**, and exactly one
    caller passes it: the acknowledgement (RADD-970). The reason is narrow and
    worth stating, because "prefer the stored subject" is otherwise the right
    answer everywhere. The ack's bracketed key IS the subject-line threading
    fallback (`parsing.extract_reply_key`) — the last resort for a client that
    drops In-Reply-To and References. At the moment the ack goes out, the stored
    thread subject is the REQUESTER'S own ("my printer is on fire"), which
    carries no key: preferring it would delete that fallback on the very message
    that is the only place it can be established. Nothing else is pinned,
    because every later message replies to one that already carried a key.

    Pinning changes the line a human reads and nothing a client threads on:
    Reply-To, In-Reply-To and References still come from the message store.

    Never raises: a caller mailing a list must not lose the rest of it to one
    unreachable address, and a reply is not worth a retry queue. The failure is
    logged AND emitted as `mail.failed` against the item, because "the customer
    never got it" being only a log line is what made it invisible to every
    screen and every rule (RADD-960).

    **`failure` says what a delivery failure MEANS to the caller** (RADD-997,
    widened to three answers by RADD-1036 — see `MailFailureReport`), and
    exactly one caller passes it: notify's mailer, which runs a retry ladder.
    The default answers for everyone else, and it is the right default — a
    reply and an ack are each sent once, so their failure is final the moment it
    happens and the event is the only record of it. A RETRYING caller is the
    different case: `mail.failed` is item-scoped and drives automations and the
    activity feed, i.e. it answers "did this person hear from us", and
    re-answering it every five seconds while the same message is still being
    attempted is noise in a stream every consumer reads. The knob is here rather
    than a rule inside `_emit_outcome` because whether another attempt is coming
    is the caller's knowledge, not this file's.

    Delivery itself, and what is recorded about it, is `_deliver` — shared with
    `send_plain_mail`.
    """
    if not to_address:
        return None
    async with _session(session) as db:
        # Per ITEM, not per instance (RADD-979): the identity the recipient
        # should see is the address their conversation arrived at.
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
) -> str | None:
    """Mail one person about NO issue in particular (RADD-983). Returns the
    Message-ID that went on the wire, or None when nothing was sent.

    `headers` as in `send_item_mail` — here there is nothing of this file's to
    collide with, so they go on the wire as given.

    The sibling of `send_item_mail`, and deliberately not a special case of it:
    a notification digest is about ten items and an automation's `send_email`
    at set arity is about none, so there is no item to thread on, no stored
    thread subject to prefer, and nothing to record in the message store. What
    it DOES share is everything that made those two senders invisible while
    they dialled `radd.smtp` themselves — the sender resolution (the default
    `mail_senders` row, environment relay as the fallback) and the
    `mail.sent`/`mail.failed` events.

    Those events are emitted with **no item subject**, the shape `mail.dropped`
    has always had: `mail.dropped` is not item-scoped "because by definition
    there is no item", and the same is true here. Automations is unaffected —
    `mail.sent`/`mail.failed` are declared `item_scoped`, so `apply_event`
    resolves no target and skips before any rule can act on one.

    **No Reply-To.** `send_item_mail` sets one because a reply belongs on the
    conversation it answers; a digest has no conversation, and pointing its
    Reply-To at the intake address would turn "reply to me about that comment"
    into a brand-new ticket in whatever project the source defaults to.

    Never raises, for `send_item_mail`'s reason: a loop mailing a list must not
    lose the rest of it to one unreachable address.
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
    attachments: tuple[MailAttachment, ...] = (),
) -> str | None:
    """One message onto one relay, and the report of what happened to it.

    The whole of what the two entry points have in common, which is why it is a
    function rather than a duplicated try/except: "never raises", "the recorded
    id is the one the SENDER REPORTS", and "the outcome is an event, not only a
    log line" are properties of the CHANNEL, and a second copy of them is a
    second copy that drifts.

    The recorded id is the sender's return value, not the one composed: SMTP
    honours a client-set id and the Gmail API replaces it, and storing an
    intended value the provider did not use makes every reply arrive
    unthreaded — days later, at a customer, with nothing raised anywhere.
    """
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
    await _emit_outcome(session, item_id, MailEvent.SENT, to_address, subject)
    return sent


def _error_text(exc: BaseException) -> str:
    """What went wrong, in one line an operator can act on (RADD-1036).

    The class name is kept beside the message because half of these carry no
    message at all — `smtplib.SMTPServerDisconnected()` stringifies to the empty
    string, and "delivery failed: " on the monitoring card is the failure this
    whole card exists to end.
    """
    return f"{type(exc).__name__}: {exc}".strip()[:MAIL_ERROR_MAX_CHARS]


async def _emit_outcome(
    session: AsyncSession,
    item_id: uuid.UUID | None,
    event_type: MailEvent,
    address: str,
    subject: str,
    *,
    error: str = "",
    given_up: bool = False,
) -> None:
    """Report what the channel did (RADD-960). Item-scoped where there IS an
    item, so a rule can flag the ticket — the whole point of emitting rather
    than logging harder.

    One event per MESSAGE (it was one per fan-out batch), because a fan-out is
    now several independent sends that can succeed and fail separately. The
    payload keeps its shape — `recipients` is a one-element list — so no rule
    written against `mail.sent` has to change.

    `item_id` is None for the itemless senders (RADD-983); the event then takes
    a synthetic entity id and names no subject, exactly as `mail.dropped` does.

    `error` and `given_up` ride only failures (RADD-1036). `given_up` is what
    separates "the relay blipped and the next attempt worked" from "the ladder
    ran out and this person will never hear from us" — the number Settings →
    Monitoring shows in red.
    """
    payload: dict[str, object] = {
        "recipients": [address],
        "recipient_count": 1,
        "subject": subject,
        # No body, for the reason in intake._mail_facts.
    }
    if event_type is MailEvent.FAILED:
        payload["error"] = error
        payload["given_up"] = given_up
    await events.emit(
        session,
        event_type=event_type,
        entity_type=MailEntity.MAIL,
        # A synthetic id rather than a nullable column: `entity_id` is the
        # events table's addressing, and an itemless mail event still needs to
        # be one row you can name.
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
    """What outbound mail did over the last `window_hours` (RADD-1036).

    Terminally-failed mail used to be invisible: notify's ladder stamps the row
    `emailed_at` when it gives up and exactly two `mail.failed` events exist,
    and nothing aggregated them — so "the customer never got it" was a fact only
    a hand-written SELECT over the events table could tell you.

    The aggregation lives HERE, beside `_emit_outcome`, because the payload
    shape is this file's and a second reader that re-states it is a reader that
    drifts. Monitoring composes it through the public seam without learning
    either the event type or the payload keys.
    """

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
    """Outbound failures in the recent past, newest first.

    Read through `events.query_events` rather than a hand-written select: the
    events table belongs to the events module, and its filtered read is already
    the public seam the admin audit view uses.
    """
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
        # A row written before RADD-1036 carries no `error` key, and an empty
        # string reads better on the card than the word "None".
        error=str(payload.get("error") or ""),
        given_up=bool(payload.get("given_up")),
    )
