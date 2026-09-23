"""Backups — the API and schedules over the core engine (spec 99).

Core, not optional: `core=True` and in the bootstrap `RADD_MODULES`. The engine
itself lives in `radd/backup/` because the CLI must restore an EMPTY database,
where no plugin registry could load; this module is only what the CLI does not
need — schedule rows, run rows, HTTP, and the events that reach the audit log.
"""

from radd.backup.types import BackupEvent
from radd.kernel import EventTypeSpec, RaddPlugin

from . import scheduler
from .router import router

plugin = RaddPlugin(
    name="backup",
    description="Scheduled and on-demand encrypted backups of the database and attachments, with restore.",
    depends_on=("auth", "events"),
    routers=(router,),
    on_startup=(scheduler.start,),
    on_shutdown=(scheduler.stop,),
    # trigger=False: these are INFRASTRUCTURE events. They belong in the audit
    # trail and on the webhook stream, but an automation acts on items, so putting
    # seven admin events in the trigger dropdown would be noise. Flip a flag if
    # "alert me when a backup fails" is ever wanted.
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
