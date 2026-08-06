import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.events import service as events

from .models import ItemWatcher, Notification, NotificationPref
from .types import NotificationType, NotifyEntity, NotifyEvent
from radd.clock import utcnow



# --- watchers ---


async def add_watchers(
    session: AsyncSession, item_id: uuid.UUID, user_ids: Iterable[uuid.UUID]
) -> None:
    """Idempotent bulk follow (auto-watch) — existing rows are left untouched."""
    rows = [{"item_id": item_id, "user_id": user_id} for user_id in set(user_ids)]
    if not rows:
        return
    await session.execute(pg_insert(ItemWatcher).values(rows).on_conflict_do_nothing())


async def watch(
    session: AsyncSession,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Manual follow — idempotent; emits item.watched (audit) only on first add."""
    if await is_watching(session, item_id, user_id):
        return
    await add_watchers(session, item_id, [user_id])
    await events.emit(
        session,
        event_type=NotifyEvent.ITEM_WATCHED,
        entity_type=NotifyEntity.WATCHER,
        entity_id=item_id,
        actor_id=user_id,
        subjects={"item": item_id},
    )


async def unwatch(
    session: AsyncSession,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    row = await session.get(ItemWatcher, (item_id, user_id))
    if row is None:
        return
    await session.delete(row)
    await events.emit(
        session,
        event_type=NotifyEvent.ITEM_UNWATCHED,
        entity_type=NotifyEntity.WATCHER,
        entity_id=item_id,
        actor_id=user_id,
        subjects={"item": item_id},
    )


async def watcher_ids(session: AsyncSession, item_id: uuid.UUID) -> list[uuid.UUID]:
    result = await session.execute(
        select(ItemWatcher.user_id).where(ItemWatcher.item_id == item_id)
    )
    return list(result.scalars())


async def is_watching(session: AsyncSession, item_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return await session.get(ItemWatcher, (item_id, user_id)) is not None


# --- notifications ---


async def create_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    type_: NotificationType,
    event_id: int | None,
    item_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    payload: dict,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        event_id=event_id,
        type=type_.value,
        item_id=item_id,
        actor_id=actor_id,
        payload=payload,
    )
    session.add(notification)
    await session.flush()
    # The realtime module (spec 27) pushes this so bells update live.
    await events.emit(
        session,
        event_type=NotifyEvent.NOTIFICATION_CREATED,
        entity_type=NotifyEntity.NOTIFICATION,
        entity_id=notification.id,
        actor_id=actor_id,
        payload={"user_id": str(user_id), "type": type_.value, "item_id": str(item_id) if item_id else None},
    )
    return notification


async def list_notifications(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    result = await session.execute(
        stmt.order_by(Notification.created_at.desc(), Notification.id).limit(limit).offset(offset)
    )
    return list(result.scalars())


async def unread_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(result.scalar_one())


async def mark_read(
    session: AsyncSession, user_id: uuid.UUID, ids: Sequence[uuid.UUID]
) -> None:
    if not ids:
        return
    await session.execute(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.id.in_(list(ids)),
            Notification.read_at.is_(None),
        )
        .values(read_at=utcnow())
    )


async def mark_all_read(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )


# --- per-user preferences (no row = all defaults) ---


async def get_prefs(session: AsyncSession, user_id: uuid.UUID) -> NotificationPref | None:
    return await session.get(NotificationPref, user_id)


async def set_prefs(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    muted_types: list[NotificationType],
    email_digest: bool,
) -> NotificationPref:
    prefs = await session.get(NotificationPref, user_id)
    if prefs is None:
        prefs = NotificationPref(user_id=user_id)
        session.add(prefs)
    prefs.muted_types = [muted.value for muted in muted_types]
    prefs.email_digest = email_digest
    await session.flush()
    return prefs


async def muted_types_by_user(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, set[str]]:
    """Consumer seam: which types each recipient has muted (absent row = none)."""
    ids = set(user_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(NotificationPref).where(NotificationPref.user_id.in_(ids))
    )
    return {prefs.user_id: set(prefs.muted_types) for prefs in result.scalars()}


async def digest_disabled_users(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """Emailer seam: recipients who opted out of the email digest."""
    ids = set(user_ids)
    if not ids:
        return set()
    result = await session.execute(
        select(NotificationPref.user_id).where(
            NotificationPref.user_id.in_(ids), NotificationPref.email_digest.is_(False)
        )
    )
    return set(result.scalars())
