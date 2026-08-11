from datetime import datetime

from pydantic import BaseModel


class DatabaseHealth(BaseModel):
    ok: bool
    postgres_version: str
    size_bytes: int
    active_connections: int


class EntityCount(BaseModel):
    key: str
    label: str
    # Approximate (pg_stat_user_tables live-tuple estimate) — instant on any
    # corpus size, which is the right trade for a glance page.
    count: int


class WorkerStatus(BaseModel):
    name: str
    last_event_id: int
    stream_head: int
    lag: int
    seconds_since_update: int


class MailFailureEntry(BaseModel):
    """One message the relay refused, as the card shows it."""

    at: datetime
    recipient: str
    subject: str
    #: The exception's class and message, capped by the emitter. Empty on rows
    #: written before RADD-1036.
    error: str
    #: The retry ladder ran out on this one — nobody is going to hear from us.
    given_up: bool


class MailHealth(BaseModel):
    """Outbound mail over the recent window (RADD-1036).

    `available=False` means the mailintake module is not loaded, which is not a
    health problem — the card is absent rather than green.
    """

    available: bool
    window_hours: int = 0
    failures: int = 0
    given_up: int = 0
    #: True when the scan hit its limit; `failures` is then a floor, not a count.
    capped: bool = False
    recent: list[MailFailureEntry] = []


class MonitoringOverview(BaseModel):
    database: DatabaseHealth
    counts: list[EntityCount]
    workers: list[WorkerStatus]
    mail: MailHealth
    # False when this API process runs web-only (RADD_RUN_WORKERS off) — the
    # consumers then live in a separate worker process; lag still tells the
    # truth, but "no movement" here may just mean "look at the worker pod".
    workers_in_process: bool
