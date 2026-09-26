"""The backup scheduler loop (spec 99 §4): each tick claims due schedules `FOR UPDATE SKIP
LOCKED` and advances `next_run_at` in the SAME transaction, so a second worker never takes the
same backup. Gated on `run_workers`, so a web-only tier does not duplicate the dumps."""

import logging

from sqlalchemy import select

from radd.config import settings
from radd.db import SessionLocal
from radd.schedule import next_run
from radd.worker import PeriodicLoop

from . import service
from .models import BackupSchedule
from radd.clock import utcnow

logger = logging.getLogger(__name__)



async def run_once() -> None:
    now = utcnow()
    async with SessionLocal() as session:
        due = (
            await session.execute(
                select(BackupSchedule)
                .where(
                    BackupSchedule.enabled.is_(True),
                    BackupSchedule.next_run_at.isnot(None),
                    BackupSchedule.next_run_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for schedule in due:
            logger.info("backup schedule %r is due", schedule.name)
            # Advance FIRST, inside the claim: a crash mid-backup must not leave
            # the row due forever, re-firing on every tick.
            schedule.next_run_at = next_run(schedule.config, now, settings.scheduler_tz)
            await service.start_backup(
                session,
                actor=None,
                include_attachments=schedule.include_attachments,
                schedule=schedule,
            )
        await session.commit()


loop = PeriodicLoop(
    run_once,
    interval=lambda: settings.backup_scheduler_interval,
    name="backup-scheduler",
    enabled=lambda: settings.run_workers,
    sleep_first=True,  # never dump during the startup burst
)


async def start() -> None:
    """Startup: fail any run the last process abandoned, seed the default
    schedule on a fresh install, then begin ticking."""
    await service.mark_interrupted()
    async with SessionLocal() as session:
        await service.ensure_default_schedule(session)
        await session.commit()
    await loop.start()


async def stop() -> None:
    await loop.stop()
