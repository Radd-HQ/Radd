"""Wire shapes for the pipeline endpoints (spec 100)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from radd.apitypes import UtcDatetime

from ..schemas import ProblemRead
from ..types import RunKind, RunStage


class RunStart(BaseModel):
    plan_id: uuid.UUID
    kind: RunKind = RunKind.DRY_RUN  # dry run is the safe default


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID | None
    snapshot_id: uuid.UUID | None
    project_id: uuid.UUID | None
    kind: RunKind
    dry_run: bool
    stage: RunStage
    counts: dict[str, int]
    problems: list[ProblemRead]
    report: dict[str, Any]
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    created_at: UtcDatetime


class RollbackStart(BaseModel):
    # Keeping the schema is the common case: fix the mapping, re-import, without
    # re-provisioning the project and its fields.
    include_schema: bool = False
    # Anything a human edited after the import is left alone unless you say not to.
    skip_edited: bool = True


class RollbackPreflight(BaseModel):
    total: int
    by_entity: dict[str, int] = Field(default_factory=dict)
    edited_since: list[str] = Field(default_factory=list)


class PendingSummary(BaseModel):
    """Cross-project references waiting for their target, grouped by project."""

    total: int
    by_project: dict[str, int] = Field(default_factory=dict)
    resolved: int = 0
