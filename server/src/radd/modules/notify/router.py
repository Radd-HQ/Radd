import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz, service as auth
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import service
from .models import Notification
from .schemas import (
    MarkReadRequest,
    NotificationActor,
    NotificationList,
    NotificationPrefsRead,
    NotificationPrefsUpdate,
    NotificationRead,
    WatcherRef,
    WatchersRead,
)
from .types import NotificationType

router = APIRouter(tags=["notify"])

Session = Annotated[AsyncSession, Depends(get_session)]

_LIFTED_KEYS = ("item_key", "item_title", "actor_name")


def _to_read(notification: Notification) -> NotificationRead:
    payload = notification.payload or {}
    actor = None
    if notification.actor_id is not None and payload.get("actor_name"):
        actor = NotificationActor(id=notification.actor_id, name=payload["actor_name"])
    return NotificationRead(
        id=notification.id,
        type=NotificationType(notification.type),
        item_id=notification.item_id,
        item_key=payload.get("item_key"),
        item_title=payload.get("item_title"),
        actor=actor,
        detail={k: v for k, v in payload.items() if k not in _LIFTED_KEYS},
        read=notification.read_at is not None,
        created_at=notification.created_at,
    )


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    session: Session,
    user: CurrentUser,
    unread: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationList:
    rows = await service.list_notifications(
        session, user.id, unread_only=unread, limit=limit, offset=offset
    )
    return NotificationList(
        notifications=[_to_read(row) for row in rows],
        unread_count=await service.unread_count(session, user.id),
    )


@router.get("/notifications/preferences", response_model=NotificationPrefsRead)
async def get_preferences(session: Session, user: CurrentUser) -> NotificationPrefsRead:
    prefs = await service.get_prefs(session, user.id)
    if prefs is None:
        return NotificationPrefsRead()  # defaults: everything on
    return NotificationPrefsRead(
        muted_types=[NotificationType(value) for value in prefs.muted_types],
        email_digest=prefs.email_digest,
    )


@router.put("/notifications/preferences", response_model=NotificationPrefsRead)
async def put_preferences(
    data: NotificationPrefsUpdate, session: Session, user: CurrentUser
) -> NotificationPrefsRead:
    prefs = await service.set_prefs(
        session, user.id, muted_types=data.muted_types, email_digest=data.email_digest
    )
    return NotificationPrefsRead(
        muted_types=[NotificationType(value) for value in prefs.muted_types],
        email_digest=prefs.email_digest,
    )


@router.post("/notifications/read", status_code=204)
async def mark_read(data: MarkReadRequest, session: Session, user: CurrentUser) -> None:
    await service.mark_read(session, user.id, data.ids)


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(session: Session, user: CurrentUser) -> None:
    await service.mark_all_read(session, user.id)


async def _readable_item_project(
    session: AsyncSession, user: CurrentUser, item_id: uuid.UUID
) -> Project:
    _item, project, _perms = await items_service.require_readable_item(session, item_id, user)
    return project


@router.put("/items/{item_id}/watch", status_code=204)
async def watch_item(item_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await _readable_item_project(session, user, item_id)  # 403/404 guard
    await service.watch(session, item_id, user.id)


@router.delete("/items/{item_id}/watch", status_code=204)
async def unwatch_item(item_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await _readable_item_project(session, user, item_id)  # 403/404 guard
    await service.unwatch(session, item_id, user.id)


@router.get("/items/{item_id}/watchers", response_model=WatchersRead)
async def item_watchers(item_id: uuid.UUID, session: Session, user: CurrentUser) -> WatchersRead:
    await _readable_item_project(session, user, item_id)
    ids = await service.watcher_ids(session, item_id)
    users = await auth.users_by_ids(session, set(ids))
    watchers = [
        WatcherRef(id=user_id, name=users[user_id].name) for user_id in ids if user_id in users
    ]
    watchers.sort(key=lambda ref: ref.name.lower())
    return WatchersRead(watching=user.id in set(ids), watchers=watchers)
