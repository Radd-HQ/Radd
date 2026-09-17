"""Contracts for grouped lists, board summaries and individual cell windows."""

import uuid
from pydantic import BaseModel, Field
from .schemas import ItemRead


class GroupPageRequest(BaseModel):
    project_id: uuid.UUID | None = None
    q: str = ""
    axis: str
    column_key: str | None = None
    lane_key: str | None = None
    summary_only: bool = False
    rows_only: bool = False
    cursor_mode: bool = False
    after: str | None = Field(None, max_length=16384)
    lane: str | None = None
    hidden_columns: list[str] = Field(default_factory=list)
    hidden_lanes: list[str] = Field(default_factory=list)
    column_order: list[str] = Field(default_factory=list)
    lane_order: list[str] = Field(default_factory=list)
    cycle_ids: list[uuid.UUID] | None = None
    cycle_scope: bool = False
    group_offset: int = Field(0, ge=0)
    item_offset: int = Field(0, ge=0)
    group_limit: int = Field(20, ge=1, le=40)
    item_limit: int = Field(25, ge=1, le=50)


class GroupCell(BaseModel):
    column: str
    lane: str
    total: int | None
    items: list[ItemRead]
    points: float | None = None
    next_cursor: str | None = None


class GroupPage(BaseModel):
    cells: list[GroupCell]
    total_groups: int
    column_totals: dict[str, int]
    lane_totals: dict[str, int]
    column_points: dict[str, float] | None = None
    column_labels: dict[str, str] = Field(default_factory=dict)
    lane_labels: dict[str, str] = Field(default_factory=dict)
    epic_refs: dict[str, dict] = Field(default_factory=dict)
