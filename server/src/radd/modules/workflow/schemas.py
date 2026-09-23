import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .types import StateCategory, TransitionCheck, TransitionMode
from radd.apitypes import UtcDatetime


class StateCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    # RADD-854: a category KEY (vocabulary row). The six builtin keys coincide
    # with the old enum values, so pre-854 payloads stay valid unchanged.
    category: str = Field(min_length=1, max_length=60)
    position: int | None = None  # None = append at the end of the workflow


class StateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    # RADD-853/854: a category KEY — re-classifies the state (and derives the
    # semantic column from the row's behaves_as) from that moment on.
    category: str | None = Field(default=None, min_length=1, max_length=60)
    position: int | None = None


class StateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    #: The SEMANTIC behaviour (derived from the vocabulary row) — what
    #: reports, sweeps and colours key off.
    category: StateCategory
    #: The VOCABULARY row the state is classified under (RADD-854).
    category_key: str
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
    # RADD-1285: performed automatically when a release is published.
    on_release: bool = False


class TransitionUpdate(BaseModel):
    # from_state_id uses the model_fields_set idiom: omitted = unchanged,
    # explicit null = the wildcard.
    from_state_id: uuid.UUID | None = None
    to_state_id: uuid.UUID | None = None
    rules: list[TransitionRule] | None = None
    applies_when: list[TransitionCondition] | None = None
    position: int | None = None
    on_release: bool | None = None


class TransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    from_state_id: uuid.UUID | None
    to_state_id: uuid.UUID
    rules: list[TransitionRule]
    applies_when: list[TransitionCondition]
    position: int
    on_release: bool = False
    created_at: UtcDatetime


class AllowedTarget(BaseModel):
    state_id: uuid.UUID
    allowed: bool
    failures: list[str]


class AllowedTransitions(BaseModel):
    """`GET /items/{id}/allowed-transitions` — the UI's graying/tooltip source."""

    mode: TransitionMode
    targets: list[AllowedTarget]


# --- state categories (RADD-854): the user-owned vocabulary tier -------------


class StateCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    behaves_as: StateCategory
    color: str | None = Field(default=None, max_length=20)
    position: int | None = None  # None = append


class StateCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    #: Custom rows only — a builtin's behaviour IS its identity. Ripples over
    #: the row's states (their derived semantic column updates in one pass).
    behaves_as: StateCategory | None = None
    color: str | None = Field(default=None, max_length=20)
    position: int | None = None


class StateCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    color: str | None
    position: int
    behaves_as: StateCategory
    is_builtin: bool
