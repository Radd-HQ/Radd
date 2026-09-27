"""Mail configuration as ROWS (RADD-958): CRUD, the capability snapshot, and the
completeness checks the poller and outbound consult. Env seeding is
`seeding.py`; preset resolution `resolve.py`. `enabled=false` is a deliberate
pause, distinct from an incomplete row — the poller skips both."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd import secretbox
from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError

from . import resolve
from .models import MailRule, MailSender, MailSource
from .types import POLLED_SOURCE_KINDS, MailEntity, MailSourceKind

logger = logging.getLogger(__name__)

#: Whether ANY enabled source/sender exists, for the SYNC kernel capability
#: check — which cannot await a query. Refreshed on seed and on every write.
_configured = {"inbound": False, "outbound": False}


def capability_state() -> dict:
    return {"enabled": _configured["inbound"] or _configured["outbound"]}


def outbound_capability() -> dict:
    """Outbound email (RADD-1389): an enabled sender ROW exists — the env SMTP host
    only seeds a row."""
    return {"enabled": _configured["outbound"]}


async def encrypt_plaintext_secrets() -> None:
    """Mailbox passwords and ingest secrets saved before RADD-1446 take their
    encrypted form. A missing secretbox key logs and skips — boot never waits on it."""
    try:
        async with SessionLocal() as session:
            for row in [*await list_sources(session), *await list_senders(session)]:
                row.secret = secretbox.adopt(row.secret)
            await session.commit()
    except secretbox.SecretBoxError as exc:
        logger.warning("mailintake: source and sender secrets stay plaintext this boot: %s", exc)


async def refresh_snapshot(session: AsyncSession) -> None:
    sources = await session.execute(select(MailSource).where(MailSource.enabled.is_(True)))
    senders = await session.execute(select(MailSender).where(MailSender.enabled.is_(True)))
    # Resolved, not raw: a preset row stores no host and still works (RADD-969).
    _configured["inbound"] = any(
        resolve.source_host(s) or s.secret for s in sources.scalars()
    )
    _configured["outbound"] = any(resolve.sender_host(s) for s in senders.scalars())


# --- reads ---------------------------------------------------------------------


async def list_sources(session: AsyncSession) -> list[MailSource]:
    rows = await session.execute(select(MailSource).order_by(MailSource.name))
    return list(rows.scalars())


async def list_senders(session: AsyncSession) -> list[MailSender]:
    rows = await session.execute(select(MailSender).order_by(MailSender.name))
    return list(rows.scalars())


async def list_rules(session: AsyncSession, source_id: uuid.UUID) -> list[MailRule]:
    rows = await session.execute(
        select(MailRule)
        .where(MailRule.source_id == source_id)
        .order_by(MailRule.position, MailRule.created_at)
    )
    return list(rows.scalars())


async def get_source(session: AsyncSession, source_id: uuid.UUID) -> MailSource:
    row = await session.get(MailSource, source_id)
    if row is None:
        raise NotFoundError(MailEntity.SOURCE, source_id)
    return row


async def get_sender(session: AsyncSession, sender_id: uuid.UUID) -> MailSender:
    row = await session.get(MailSender, sender_id)
    if row is None:
        raise NotFoundError(MailEntity.SENDER, sender_id)
    return row


async def polled_sources(session: AsyncSession) -> list[MailSource]:
    """Enabled polled sources with somewhere to connect (RESOLVED values, so a
    preset row is complete — RADD-969). A half-filled row is skipped silently
    rather than erroring every 60 seconds."""
    rows = await session.execute(
        select(MailSource).where(
            MailSource.kind.in_([k.value for k in POLLED_SOURCE_KINDS]),
            MailSource.enabled.is_(True),
        )
    )
    return [row for row in rows.scalars() if resolve.source_pollable(row)]


async def source_for_address(session: AsyncSession, address: str) -> MailSource | None:
    """The webhook source for this envelope recipient, matched case-insensitively.
    A source with no address matches NOTHING (else any recipient reaches it)."""
    if not address:
        return None
    wanted = address.strip().lower()
    rows = await session.execute(
        select(MailSource).where(
            MailSource.kind == MailSourceKind.WEBHOOK.value, MailSource.enabled.is_(True)
        )
    )
    for row in rows.scalars():
        if row.address and row.address.strip().lower() == wanted:
            return row
    return None


async def default_sender(session: AsyncSession) -> MailSender | None:
    """The sender outbound uses: the default if one is marked, else the only
    enabled one. Ambiguity resolves to None rather than a guess — silently
    sending as the wrong identity is worse than not sending."""
    rows = await session.execute(select(MailSender).where(MailSender.enabled.is_(True)))
    enabled = [row for row in rows.scalars() if resolve.sender_host(row)]
    if not enabled:
        return None
    marked = [row for row in enabled if row.is_default]
    if marked:
        return marked[0]
    return enabled[0] if len(enabled) == 1 else None


async def bound_sender(session: AsyncSession, source_id: uuid.UUID) -> MailSender | None:
    """The sender a source ANSWERS FROM (RADD-979), when it can still send;
    disabled or deleted falls through to None (then the default sender) — pausing
    a relay must not stop the mail on every source pointed at it."""
    source = await session.get(MailSource, source_id)
    if source is None or source.sender_id is None:
        return None
    sender = await session.get(MailSender, source.sender_id)
    if sender is None or not sender.enabled or not resolve.sender_host(sender):
        return None
    return sender


async def any_bound_sender(session: AsyncSession) -> bool:
    """Does ANY source name a sender that could send? The second half of
    `transport.outbound_configured` (RADD-979)."""
    rows = await session.execute(
        select(MailSender)
        .join(MailSource, MailSource.sender_id == MailSender.id)
        .where(MailSender.enabled.is_(True))
    )
    return any(resolve.sender_host(row) for row in rows.scalars())


async def own_addresses(session: AsyncSession) -> set[str]:
    """Every address this instance sends AS or is reached at — the self-loop
    guard's ONE comparison set (RADD-959/970): source addresses and usernames,
    sender from/reply-to, and the env values as a fallback for an instance whose
    rows are not seeded yet. Two definitions of "us" would silently disagree.
    """
    found: set[str] = set()
    for source in await list_sources(session):
        found.update({source.address, source.username})
    for sender in await list_senders(session):
        found.update({sender.from_address, sender.reply_to})
    from email.utils import parseaddr

    found.update({parseaddr(settings.smtp_from_address)[1], settings.email_ingest_address})
    return {parseaddr(a)[1].strip().lower() for a in found if a and a.strip()}


# --- writes --------------------------------------------------------------------


def _assert_source_reachable(row: MailSource) -> None:
    """A hand-configured mailbox needs a host; a preset kind does not. Refused on
    Save (RADD-969): a silently ignored source looks, from the form, like one that
    works."""
    if resolve.source_needs_host(row):
        raise ConflictError(
            MailEntity.SOURCE,
            reason=f"an {row.kind} source needs a host — Gmail and Outlook supply their own",
        )


def _assert_sender_reachable(row: MailSender) -> None:
    if resolve.sender_needs_host(row):
        raise ConflictError(
            MailEntity.SENDER,
            reason=f"an {row.kind} sender needs a host — Gmail and Outlook supply their own",
        )


async def save_source(session: AsyncSession, row: MailSource) -> MailSource:
    _assert_source_reachable(row)
    session.add(row)
    await session.flush()
    await refresh_snapshot(session)
    return row


async def save_sender(session: AsyncSession, row: MailSender) -> MailSender:
    _assert_sender_reachable(row)
    if row.is_default:
        # Exactly one default, cleared here so "make default" is one API call.
        others = await session.execute(select(MailSender).where(MailSender.id != row.id))
        for other in others.scalars():
            other.is_default = False
    session.add(row)
    await session.flush()
    await refresh_snapshot(session)
    return row


async def delete_source(session: AsyncSession, source_id: uuid.UUID) -> None:
    await session.delete(await get_source(session, source_id))
    await session.flush()
    await refresh_snapshot(session)


async def delete_sender(session: AsyncSession, sender_id: uuid.UUID) -> None:
    await session.delete(await get_sender(session, sender_id))
    await session.flush()
    await refresh_snapshot(session)


async def next_rule_position(session: AsyncSession, source_id: uuid.UUID) -> float:
    rows = await list_rules(session, source_id)
    return (rows[-1].position + 1.0) if rows else 1.0

