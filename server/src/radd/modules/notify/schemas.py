import uuid
from typing import Any

from pydantic import BaseModel, Field

from .types import Channel, NotificationType, RuleScope
from radd.apitypes import UtcDatetime


class NotificationActor(BaseModel):
    id: uuid.UUID
    name: str


class NotificationRead(BaseModel):
    id: uuid.UUID
    type: NotificationType
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
    """One row of the matrix, served from the server's vocabulary (spec 118).

    The SPA used to hold its own label map, so adding a kind meant editing an
    enum on one side of the wire and a `Record<>` on the other — two lists that
    could disagree with nothing to catch it. The rows come from
    `notify.kinds.NOTIFICATION_KINDS` now, in that order.
    """

    kind: NotificationType
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
    channels: dict[NotificationType, Channel]


class NotificationRuleWrite(BaseModel):
    scope: RuleScope
    scope_id: uuid.UUID | None = None
    channels: dict[NotificationType, Channel]


class NotificationPrefsRead(BaseModel):
    """GET/PUT /notifications/preferences — the caller's whole notification policy.

    Vocabulary + defaults + rules, so the settings page can render an
    inheritance-aware matrix without a single hardcoded table of its own:
    `kinds` gives the rows, `scopes` the relationship columns, `defaults` what an
    unset cell resolves to, and `rules` what the person actually saved.
    """

    kinds: list[NotificationKindRead]
    #: The relationship columns, in display order (`own`, `participating`, `teams`).
    scopes: list[RuleScope]
    #: {scope: {kind: channel}} for the relationship columns — the inherited value.
    defaults: dict[RuleScope, dict[NotificationType, Channel]]
    rules: list[NotificationRuleRead]
    email_digest: bool = True


class NotificationPrefsUpdate(BaseModel):
    """Full replace — `rules` is authoritative, absent is not "unchanged".

    Required for that reason: a client that omitted it would be silently
    resetting the matrix, and failing loudly beats wiping preferences. Removing
    a subscription IS leaving its row out, which is only expressible when the
    whole set is sent.

    The bound is three relationship rows plus room for far more subscriptions
    than a person could read: a full replace with no ceiling is one request that
    writes as many rows as the caller cares to name, and "the client would never
    send that" is not a limit. Nobody legitimately hits 200 — the picker offers
    each target once — so a request that does is not a preferences save.
    """

    rules: list[NotificationRuleWrite] = Field(max_length=200)
    email_digest: bool
