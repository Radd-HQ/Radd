"""Mail configuration as ROWS (RADD-958).

Email was the last subsystem reading its configuration from the environment on
every use. Sign-in (spec 110), Storage (102) and AI (101) are all rows seeded
once from env, and this brings mail in line — which is the difference between
"an operator edits sops and restarts pods" and "an admin fills in a form".

**The spec-101 rule:** env seeds the first row on an EMPTY database and is never
read again. Editing `RADD_SMTP_*` on an instance that already has a sender row
does nothing, deliberately — two sources of truth for one setting is how a
screen ends up disagreeing with the running system.

`enabled` is separate from "configured". A source with no host is incomplete; a
source with a host and `enabled=false` is a deliberate pause. The poller skips
both, but only the second is a choice someone made.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import NotFoundError

from .models import MailRule, MailSender, MailSource
from .types import MailEntity, MailSenderKind, MailSourceKind

logger = logging.getLogger(__name__)

#: Whether ANY enabled source/sender exists, for the SYNC kernel capability
#: check — which cannot await a query. Refreshed on seed and on every write.
_configured = {"inbound": False, "outbound": False}


def capability_state() -> dict:
    return {"enabled": _configured["inbound"] or _configured["outbound"]}


async def refresh_snapshot(session: AsyncSession) -> None:
    sources = await session.execute(select(MailSource).where(MailSource.enabled.is_(True)))
    senders = await session.execute(select(MailSender).where(MailSender.enabled.is_(True)))
    _configured["inbound"] = any(s.host or s.secret for s in sources.scalars())
    _configured["outbound"] = any(s.host for s in senders.scalars())


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
    """Enabled IMAP sources with somewhere to connect — what the poller walks.

    A source missing its host is skipped silently: half-filled configuration is
    the normal state of a form someone is still working on, and it must not
    produce a connection error every 60 seconds.
    """
    rows = await session.execute(
        select(MailSource).where(
            MailSource.kind == MailSourceKind.IMAP.value, MailSource.enabled.is_(True)
        )
    )
    return [row for row in rows.scalars() if row.host and row.username]


async def source_for_address(session: AsyncSession, address: str) -> MailSource | None:
    """The webhook source that accepts mail for this envelope recipient.

    Matched case-insensitively on the whole address. A push source with no
    address configured matches nothing rather than everything — the permissive
    reading would let any recipient reach any tenant's ingest.
    """
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
    enabled = [row for row in rows.scalars() if row.host]
    if not enabled:
        return None
    marked = [row for row in enabled if row.is_default]
    if marked:
        return marked[0]
    return enabled[0] if len(enabled) == 1 else None


async def own_addresses(session: AsyncSession) -> set[str]:
    """Every address this instance sends as or receives at — the self-loop
    guard's comparison set, now from rows (RADD-959 unified it; this moves it
    off env). Falls back to the env values so an instance mid-migration, with
    rows not yet seeded, still has a working guard."""
    found: set[str] = set()
    for source in await list_sources(session):
        found.update({source.address, source.username})
    for sender in await list_senders(session):
        found.update({sender.from_address, sender.reply_to})
    from email.utils import parseaddr

    found.update({parseaddr(settings.smtp_from_address)[1], settings.email_ingest_address})
    return {parseaddr(a)[1].strip().lower() for a in found if a and a.strip()}


# --- writes --------------------------------------------------------------------


async def save_source(session: AsyncSession, row: MailSource) -> MailSource:
    session.add(row)
    await session.flush()
    await refresh_snapshot(session)
    return row


async def save_sender(session: AsyncSession, row: MailSender) -> MailSender:
    if row.is_default:
        # Exactly one default. Clearing the others here rather than in a
        # constraint keeps "make this the default" a single API call.
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


# --- env seeding (once, on an empty database) -----------------------------------


async def seed_from_env() -> None:
    """Create the first source/sender from env, exactly once.

    Runs at startup. Anything already in the table means the operator has taken
    ownership through the UI, and env is not consulted again — including when it
    changes, which is the property that stops the two disagreeing.
    """
    async with SessionLocal() as session:
        try:
            await _seed(session)
            await refresh_snapshot(session)
            await session.commit()
        except Exception:  # noqa: BLE001 — never let seeding break startup
            logger.warning("mailintake: env seeding failed (continuing)", exc_info=True)
            await session.rollback()


async def _seed(session: AsyncSession) -> None:
    if settings.mail_imap_host and not (await session.execute(select(MailSource.id))).first():
        session.add(
            MailSource(
                name="Inbox (from environment)",
                kind=MailSourceKind.IMAP.value,
                address=settings.email_ingest_address or settings.mail_imap_username,
                host=settings.mail_imap_host,
                port=settings.mail_imap_port,
                username=settings.mail_imap_username,
                secret=settings.mail_imap_password,
                folder=settings.mail_imap_folder,
                default_project_id=await _project_id(session, settings.mail_project_key),
            )
        )
        logger.info("mailintake: seeded an IMAP source from the environment")
    elif settings.email_ingest_secret and not (
        await session.execute(select(MailSource.id))
    ).first():
        session.add(
            MailSource(
                name="Webhook (from environment)",
                kind=MailSourceKind.WEBHOOK.value,
                address=settings.email_ingest_address,
                secret=settings.email_ingest_secret,
                default_project_id=await _project_id(session, settings.mail_project_key),
            )
        )
        logger.info("mailintake: seeded a webhook source from the environment")

    if settings.smtp_host and not (await session.execute(select(MailSender.id))).first():
        session.add(
            MailSender(
                name="SMTP (from environment)",
                kind=MailSenderKind.SMTP.value,
                is_default=True,
                from_address=settings.smtp_from_address,
                reply_to=settings.email_ingest_address,
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                secret=settings.smtp_password,
                starttls=settings.smtp_starttls,
            )
        )
        logger.info("mailintake: seeded an SMTP sender from the environment")
    await session.flush()


async def _project_id(session: AsyncSession, key: str) -> uuid.UUID | None:
    if not key:
        return None
    from radd.modules.projects import service as projects_service

    for project in await projects_service.list_projects(session):
        if project.key == key.upper():
            return project.id
    return None
