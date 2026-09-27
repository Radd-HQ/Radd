"""Env → the first mail rows, exactly once (RADD-958). The spec-101 rule: env
seeds the first source/sender on an EMPTY database and is never read again, so
editing `RADD_SMTP_*` later deliberately does nothing — one source of truth.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd import secretbox
from radd.config import settings
from radd.db import SessionLocal

from . import registry
from .models import MailSender, MailSource
from .types import MailSenderKind, MailSourceKind

logger = logging.getLogger(__name__)


async def seed_from_env() -> None:
    """Create the first source/sender from env at startup, exactly once."""
    async with SessionLocal() as session:
        try:
            await seed(session)
            await registry.refresh_snapshot(session)
            await session.commit()
        except Exception:  # noqa: BLE001 — never let seeding break startup
            logger.warning("mailintake: env seeding failed (continuing)", exc_info=True)
            await session.rollback()


async def seed(session: AsyncSession) -> None:
    """Env seeds an SMTP sender and an IMAP/webhook source — never a preset kind
    (RADD-969): an env-named host IS the custom kind."""
    if settings.mail_imap_host and not (await session.execute(select(MailSource.id))).first():
        session.add(
            MailSource(
                name="Inbox (from environment)",
                kind=MailSourceKind.IMAP.value,
                address=settings.email_ingest_address or settings.mail_imap_username,
                host=settings.mail_imap_host,
                port=settings.mail_imap_port,
                username=settings.mail_imap_username,
                secret=secretbox.seal(settings.mail_imap_password),
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
                secret=secretbox.seal(settings.email_ingest_secret),
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
                secret=secretbox.seal(settings.smtp_password),
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
