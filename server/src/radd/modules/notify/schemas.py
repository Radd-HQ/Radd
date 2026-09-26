import uuid
from typing import Any

from pydantic import BaseModel, field_validator, Field

from .types import Channel, RuleScope
from radd.apitypes import UtcDatetime


class NotificationActor(BaseModel):
    id: uuid.UUID
    name: str


class NotificationRead(BaseModel):
    id: uuid.UUID
    #: A `NotificationType`, or a plugin's kind key (RADD-1326).
    type: str
    item_id: uuid.UUID | None
    item_key: str | None
    item_title: str | None
    actor: NotificationActor | None
    # Type-specific extras: excerpt, from/to, source, visibility.
    detail: dict[str, Any]
    read: bool
    created_at: UtcDatetime


class NotificationList(BaseModel):
    notifications: list[NotificationRead]
    unread_count: int


class MarkReadRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)


class WatcherRef(BaseModel):
    id: uuid.UUID
    name: str


class WatchersRead(BaseModel):
    watching: bool
    watchers: list[WatcherRef]


class NotificationKindRead(BaseModel):
    """One matrix row, from the kind registry (spec 118)."""

    kind: str  # RADD-1326: a registry key — core or contributed
    label: str
    description: str
    #: Addressed at a person by the event itself — resolves through `own` only,
    #: which is why the settings page greys the other columns for these.
    personal: bool


class NotificationRuleRead(BaseModel):
    """One saved rule: a scope, an optional target, and a SPARSE channel map."""

    scope: RuleScope
    scope_id: uuid.UUID | None = None
    #: Resolved name of the project/space/team — for display only, and None when
    #: the target has been deleted (the row is then dead but harmless).
    scope_label: str | None = None
    channels: dict[str, Channel]


class NotificationRuleWrite(BaseModel):
    scope: RuleScope
    scope_id: uuid.UUID | None = None
    channels: dict[str, Channel]

    @field_validator("channels")
    @classmethod
    def _known_kinds(cls, channels: dict[str, Channel]) -> dict[str, Channel]:
        """A kind is a REGISTRY key since RADD-1326 (a plugin may add one), so
        the enum can no longer be the validator — the registry is."""
        from .kinds import every_kind

        unknown = sorted(set(channels) - set(every_kind()))
        if unknown:
            raise ValueError(f"unknown notification kind(s): {', '.join(unknown)}")
        return channels


class NotificationPrefsRead(BaseModel):
    """The caller's whole policy: `kinds` (rows), `scopes` (columns), `defaults`,
    `rules`."""

    kinds: list[NotificationKindRead]
    #: The relationship columns, in display order (`own`, `participating`, `teams`).
    scopes: list[RuleScope]
    #: {scope: {kind: channel}} for the relationship columns — the inherited value.
    defaults: dict[RuleScope, dict[str, Channel]]
    rules: list[NotificationRuleRead]
    email_digest: bool = True


class NotificationPrefsUpdate(BaseModel):
    """Full replace — `rules` is required: an omitted list would silently reset
    the matrix, and removing a subscription IS leaving its row out. Bounded at 200."""

    rules: list[NotificationRuleWrite] = Field(max_length=200)
    email_digest: bool
