"""Mail configuration as ROWS (RADD-958).

Email was the last subsystem reading its configuration from the environment on
every use. Sign-in (spec 110), Storage (102) and AI (101) are all rows seeded
once from env, and this brings mail in line — which is the difference between
"an operator edits sops and restarts pods" and "an admin fills in a form".

Rows in, rows out: CRUD, the capability snapshot, and the completeness checks
the poller and outbound consult. Env seeding lives in `seeding.py`; a row's
connection details are resolved against its kind's preset in `resolve.py`.

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


async def refresh_snapshot(session: AsyncSession) -> None:
    sources = await session.execute(select(MailSource).where(MailSource.enabled.is_(True)))
    senders = await session.execute(select(MailSender).where(MailSender.enabled.is_(True)))
    # Resolved, not raw: a Gmail row stores no host and is nonetheless a working
    # inbound path (RADD-969). Reading the column here would report mail as
    # unconfigured on an instance that is happily polling.
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
    """Enabled polled sources with somewhere to connect — what the poller walks.

    Every IMAP-transported kind is included (RADD-969): Gmail and Outlook are
    the same poll against a host the preset supplies, so the completeness check
    reads RESOLVED values — a Gmail row carrying only an address, a username and
    an app password is complete.

    A source missing its host is skipped silently: half-filled configuration is
    the normal state of a form someone is still working on, and it must not
    produce a connection error every 60 seconds.
    """
    rows = await session.execute(
        select(MailSource).where(
            MailSource.kind.in_([k.value for k in POLLED_SOURCE_KINDS]),
            MailSource.enabled.is_(True),
        )
    )
    return [row for row in rows.scalars() if resolve.source_pollable(row)]


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
    enabled = [row for row in rows.scalars() if resolve.sender_host(row)]
    if not enabled:
        return None
    marked = [row for row in enabled if row.is_default]
    if marked:
        return marked[0]
    return enabled[0] if len(enabled) == 1 else None


async def own_addresses(session: AsyncSession) -> set[str]:
    """Every address this instance sends AS or can be reached at — the self-loop
    guard's comparison set.

    **THE definition, and now the only one** (RADD-959 unified two; RADD-970
    deleted the env-only copy that had survived in `loops.py`). It was once the
    webhook building the set from the SMTP from-address plus the ingest address
    and the poller building it from the from-address plus the IMAP account, so
    which addresses counted as "us" depended on how the message arrived. The
    day two such definitions disagree, the guard stops firing on one path with
    nothing raised anywhere.

    Under the Migadu topology this is `agent@radd-hq.com` (what Radd sends as)
    ∪ `help@radd-hq.com` (what it polls). Both matter: mail from the first
    landing in the second is precisely the loop.

    Falls back to the env values so an instance mid-migration, with rows not yet
    seeded, still has a working guard.
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
    """A hand-configured mailbox needs a host typed; a preset kind does not.

    Refused rather than saved-and-skipped (RADD-969): a source the poller
    silently ignores is indistinguishable, from the form, from one that works.
    The silence is right for a row someone is still editing and wrong for the
    moment they press Save.
    """
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

