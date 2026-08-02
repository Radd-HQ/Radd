import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .types import StateCategory, TransitionCheck, TransitionMode
from radd.apitypes import UtcDatetime


class StateCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    category: StateCategory
    position: int | None = None  # None = append at the end of the workflow


class StateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    position: int | None = None


class StateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    category: StateCategory
    position: int
    is_default: bool
    created_at: UtcDatetime


class StateRef(BaseModel):
    """Compact embed for entities that carry a state (e.g. work items)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: StateCategory


class TransitionRule(BaseModel):
    check: TransitionCheck
    params: dict[str, Any] = Field(default_factory=dict)


class TransitionCondition(BaseModel):
    """One applies-when condition (spec 107 follow-up) — the same shape a
    require_field rule's params carry, without the check wrapper."""

    kind: str
    key: str
    op: str
    type: str | None = None
    values: list[str] | None = None
    display: list[str] | None = None


class TransitionCreate(BaseModel):
    project_id: uuid.UUID
    from_state_id: uuid.UUID | None = None  # None = wildcard (any source state)
    to_state_id: uuid.UUID
    rules: list[TransitionRule] = Field(default_factory=list)
    # Empty = the row governs every item making this move (spec 107 follow-up).
    applies_when: list[TransitionCondition] = Field(default_factory=list)
    position: int | None = None  # None = append


class TransitionUpdate(BaseModel):
    # from_state_id uses the model_fields_set idiom: omitted = unchanged,
    # explicit null = the wildcard.
    from_state_id: uuid.UUID | None = None
    to_state_id: uuid.UUID | None = None
    rules: list[TransitionRule] | None = None
    applies_when: list[TransitionCondition] | None = None
    position: int | None = None


class TransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    from_state_id: uuid.UUID | None
    to_state_id: uuid.UUID
    rules: list[TransitionRule]
    applies_when: list[TransitionCondition]
    position: int
    created_at: UtcDatetime


class AllowedTarget(BaseModel):
    state_id: uuid.UUID
    allowed: bool
    failures: list[str]


class AllowedTransitions(BaseModel):
    """`GET /items/{id}/allowed-transitions` — the UI's graying/tooltip source."""

    mode: TransitionMode
    targets: list[AllowedTarget]
