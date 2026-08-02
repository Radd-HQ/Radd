import uuid
from typing import Any

from pydantic import BaseModel, Field

from .types import NotificationType
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
    """GET/PUT /notifications/preferences — the caller's own settings."""

    muted_types: list[NotificationType] = []
    email_digest: bool = True


class NotificationPrefsUpdate(BaseModel):
    muted_types: list[NotificationType]
    email_digest: bool
