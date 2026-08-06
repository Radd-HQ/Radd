"""API shapes for backups (spec 99 §5)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from radd.schedule import ScheduleKind, validate_config


class ScheduleConfig(BaseModel):
    """The shared schedule vocabulary — interval, daily, weekly, monthly, cron.

    Monthly and cron arrived with RADD-909/910 for automations and land here for
    free, because both modules store the same config and validate it through the
    same rules in `radd.schedule`."""

    kind: ScheduleKind
    minutes: int | None = None
    time: str | None = None  # HH:MM, in settings.scheduler_tz
    weekdays: list[int] | None = None  # 0 = Monday
    day: int | None = Field(default=None, ge=1, le=31)
    expression: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> "ScheduleConfig":
        validate_config(self.model_dump(exclude_none=True))
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
