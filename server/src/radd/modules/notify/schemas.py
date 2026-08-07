import uuid
from typing import Any

from pydantic import BaseModel, Field

from .types import NotificationType, default_email_types
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


class NotificationPrefsRead(BaseModel):
    """GET/PUT /notifications/preferences — the caller's own channel matrix.

    Two per-type lists, read as: inbox = NOT in `muted_types`; email = in
    `email_types`. Email implies inbox (a muted type is never mailed), so the
    response is always the normalised pair the server stored.

    The field defaults ARE the no-row answer the router returns.
    """

    muted_types: list[NotificationType] = []
    email_types: list[NotificationType] = Field(default_factory=default_email_types)
    email_digest: bool = True


class NotificationPrefsUpdate(BaseModel):
    """Full replace — every list is authoritative, absent is not "unchanged".

    `email_types` is required for that reason: a client that omitted it would be
    silently resetting the matrix, and failing loudly beats wiping preferences.
    """

    muted_types: list[NotificationType]
    email_types: list[NotificationType]
    email_digest: bool
