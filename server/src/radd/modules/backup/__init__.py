"""Backups — schedules, runs, HTTP and events over the core engine (spec 99). The engine
lives in `radd/backup/` because the CLI must restore an EMPTY database, where no plugin
registry could load."""

from radd.backup.types import BackupEvent
from radd.kernel import EntityLinkSpec
from radd.kernel import EventTypeSpec, RaddPlugin

from . import scheduler
from .router import router

plugin = RaddPlugin(
    name="backup",
    entity_links=(
        EntityLinkSpec('backup_schedule', ('/settings/backups',)),
    ),
    description="Scheduled and on-demand encrypted backups of the database and attachments, with restore.",
    depends_on=("auth", "events"),
    routers=(router,),
    on_startup=(scheduler.start,),
    on_shutdown=(scheduler.stop,),
    # Infrastructure events: audit trail and webhooks, not automation triggers.
    event_types=(
        EventTypeSpec(BackupEvent.CREATED, "Backup created", "Backups", trigger=False),
        EventTypeSpec(BackupEvent.DELETED, "Backup deleted", "Backups", trigger=False),
        EventTypeSpec(BackupEvent.UPLOADED, "Backup uploaded", "Backups", trigger=False),
        EventTypeSpec(BackupEvent.RESTORED, "Backup restored", "Backups", trigger=False),
        EventTypeSpec(BackupEvent.SCHEDULE_CREATED, "Backup schedule created", "Backups", trigger=False),
        EventTypeSpec(
            BackupEvent.SCHEDULE_UPDATED, "Backup schedule updated", "Backups",
            has_changes=True, trigger=False,
        ),
        EventTypeSpec(BackupEvent.SCHEDULE_DELETED, "Backup schedule deleted", "Backups", trigger=False),
    ),
)
