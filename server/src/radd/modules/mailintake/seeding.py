"""Env → the first mail rows, exactly once (RADD-958).

**The spec-101 rule:** env seeds the first source/sender on an EMPTY database
and is never read again. Editing `RADD_SMTP_*` on an instance that already has a
sender row does nothing, deliberately — two sources of truth for one setting is
how a screen ends up disagreeing with the running system.

Split out of `registry` (RADD-969), which is now purely rows in / rows out. This
is startup behaviour, runs once in the life of a database, and reads a config
object nothing else here touches.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal

from . import registry
from .models import MailSender, MailSource
from .types import MailSenderKind, MailSourceKind

logger = logging.getLogger(__name__)


async def seed_from_env() -> None:
    """Create the first source/sender from env, exactly once.

    Runs at startup. Anything already in the table means the operator has taken
    ownership through the UI, and env is not consulted again — including when it
    changes, which is the property that stops the two disagreeing.
    """
    async with SessionLocal() as session:
        try:
            await seed(session)
            await registry.refresh_snapshot(session)
            await session.commit()
        except Exception:  # noqa: BLE001 — never let seeding break startup
            logger.warning("mailintake: env seeding failed (continuing)", exc_info=True)
            await session.rollback()


async def seed(session: AsyncSession) -> None:
    """Env seeds an SMTP sender and an IMAP/webhook source — never a preset kind.

    Deliberate (RADD-969): `RADD_SMTP_HOST` names a host, and a row that names
    its host IS the custom kind. Guessing "this looks like Gmail, make it a
    preset row" would rewrite an operator's explicit configuration into
    something that resolves elsewhere later.
    """
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
