"""API shapes for backups (spec 99 §5)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from radd.schedule import ScheduleKind, parse_hh_mm


class ScheduleConfig(BaseModel):
    """{kind, minutes | time, weekdays} — the shared schedule vocabulary."""

    kind: ScheduleKind
    minutes: int | None = Field(default=None, ge=5)
    time: str | None = None  # HH:MM, in settings.scheduler_tz
    weekdays: list[int] = Field(default_factory=list)  # 0 = Monday

    @model_validator(mode="after")
    def _check(self) -> "ScheduleConfig":
        if self.kind is ScheduleKind.INTERVAL:
            if self.minutes is None:
                raise ValueError("an interval schedule needs `minutes` (>= 5)")
            return self
        if not self.time:
            raise ValueError(f"a {self.kind.value} schedule needs `time` (HH:MM)")
        try:
            parse_hh_mm(self.time)
        except ValueError as exc:
            raise ValueError(f"invalid time {self.time!r} — expected HH:MM") from exc
        if self.kind is ScheduleKind.WEEKLY and not self.weekdays:
            raise ValueError("a weekly schedule needs at least one weekday (0=Mon)")
        if self.kind is ScheduleKind.DAILY and self.weekdays:
            raise ValueError("a daily schedule does not take `weekdays`")
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays are 0 (Mon) to 6 (Sun)")
        return self


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    config: ScheduleConfig
    enabled: bool = True
    include_attachments: bool = True
    keep_last: int | None = Field(default=7, ge=1)
    keep_days: int | None = Field(default=None, ge=1)


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: ScheduleConfig | None = None
    enabled: bool | None = None
    include_attachments: bool | None = None
    keep_last: int | None = Field(default=None, ge=1)
    keep_days: int | None = Field(default=None, ge=1)


class ScheduleRead(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    config: dict[str, Any]
    include_attachments: bool
    keep_last: int | None
    keep_days: int | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None


class BackupRead(BaseModel):
    """One artifact on disk. `restorable` is decided here so the UI never offers
    a restore that will be refused at click time."""

    name: str
    size_bytes: int
    created_at: datetime
    kind: str
    complete: bool
    encrypted: bool
    key_id: str | None
    includes_attachments: bool
    schema_version: int | None
    radd_version: str | None
    created_by: str | None
    restorable: bool
    problem: str | None


class RunRead(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    stage: str
    artifact_name: str | None
    size_bytes: int | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None


class BackupCreateRequest(BaseModel):
    include_attachments: bool | None = None


class RestoreRequest(BaseModel):
    """`confirm` must equal the database name — the same guard the CLI prompts
    for, so a mis-click cannot replace an instance."""

    confirm: str
    override_compatibility: bool = False


class ToolRead(BaseModel):
    path: str | None
    version: str | None


class StatusRead(BaseModel):
    """Where a broken deploy becomes visible before it matters."""

    directory: str
    directory_writable: bool
    directory_problem: str | None
    free_bytes: int | None
    pg_dump: ToolRead
    pg_restore: ToolRead
    tools_problem: str | None
    encryption_enabled: bool
    key_id: str | None
    key_file: str
    key_problem: str | None
    schema_version: int
    maintenance: bool
    next_run_at: datetime | None
