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


class MonitoringOverview(BaseModel):
    database: DatabaseHealth
    counts: list[EntityCount]
    workers: list[WorkerStatus]
    # False when this API process runs web-only (RADD_RUN_WORKERS off) — the
    # consumers then live in a separate worker process; lag still tells the
    # truth, but "no movement" here may just mean "look at the worker pod".
    workers_in_process: bool
