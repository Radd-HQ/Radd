import uuid
from collections.abc import Collection, Iterable, Sequence
from typing import TypeGuard

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.auth.types import UserSource
from radd.modules.events import service as events

from .models import ItemWatcher, Notification, NotificationPref
from .types import (
    SYSTEM_ACTOR_ID,
    NotificationType,
    NotifyEntity,
    NotifyEvent,
    default_email_type_values,
)
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


# --- who has a mailbox ---


def mailable_user(user: User | None) -> TypeGuard[User]:
    """Is there a PERSON's mailbox behind this account? (RADD-996)

    Both email loops ask this before composing anything, and both treat a False
    the way they have always treated an inactive or address-less recipient:
    stamp the row and move on. That is deliberate — the answer is a property of
    the ACCOUNT, not of this attempt, so a retry can only produce the same
    answer more slowly. (A delivery failure is the other case, and it retries;
    see `retry.py`.)

    Four kinds of account are not a person to mail:

    * inactive, and address-less — the two this predicate absorbed;
    * `UserSource.SERVICE` — a spec-113 service account. `radd-agent@service.
      radd.local` does not receive; a key's account carries an address because
      the column requires one, not because anyone reads it. Live evidence: those
      accounts have been getting notification mail since v0.29.0, and the relay
      was rate-limited for repeatedly posting to addresses that bounce;
    * the system actor — `automation@radd.system`, the identity mail intake and
      every engine write carry.

    Inbox rows for a service account are left alone: they cost nothing, and a
    key's owner reading its notifications through the API is a coherent thing to
    want. Mail is the part with a bill attached. The system actor is refused a
    row outright — `create_notification` — because nothing reads its inbox.
    """
    if user is None or not user.active or not user.email:
        return False
    if user.id == SYSTEM_ACTOR_ID:
        return False
    return user.source != UserSource.SERVICE.value


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
    muted_types: Collection[str] | None = None,
) -> Notification | None:
    """Write one notification for one recipient — unless they MUTED this type.

    The mute check lives here because this is the one function every producer
    calls (RADD-971). It used to live in the outbox consumer alone, so the two
    types created by a direct call — `automation` (automations/engine.py) and
    `page_updated` (pages/watchers.py) — never saw a preference at all: their
    checkboxes on Settings → Profile changed nothing. Enforcing at the write
    means a new producer inherits the preference instead of re-implementing it.

    `muted_types` is an optional PREFETCH for callers that fan out to a known
    recipient set (`muted_types_by_user` resolves the whole set in one query, so
    the loop costs nothing per row). `None` means "look it up" — a caller that
    forgets it is slower, never wrong. Returns None when the type was muted.
    """
    # RADD-996: nobody reads the system actor's inbox, so it is not told things.
    #
    # This is also what settles the CLEANUP question the same bug raised. The
    # planner no longer follows the system actor, but `item_watchers` already
    # holds a row for it on every ticket that has ever arrived by email, and
    # those rows keep arriving here through the ordinary watcher fan-out. They
    # are left in place: a watcher row is inert once nothing is planned from it,
    # and deleting rows in a migration to tidy a list nobody displays is a
    # destructive write bought for cosmetics. This line is what makes leaving
    # them cost nothing — the alternative was a DELETE that would have to be
    # written again the next time something auto-watched a robot.
    if user_id == SYSTEM_ACTOR_ID:
        return None
    if muted_types is None:
        prefs = await get_prefs(session, user_id)
        muted_types = prefs.muted_types if prefs is not None else ()
    if type_.value in muted_types:
        return None
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
    email_types: list[NotificationType],
    email_digest: bool,
) -> NotificationPref:
    """Full replace of one user's channel matrix. Returns the NORMALISED row.

    A muted type is dropped from `email_types` here rather than 422'd: muting
    already silences both channels by construction (no row, nothing to mail), so
    "email me about X, but never notify me about X" is not a conflict to resolve
    — it is a statement with one meaning. The UI cannot produce it; a raw API
    caller gets that meaning stored instead of a contradiction, and reads it
    back in the response.
    """
    prefs = await session.get(NotificationPref, user_id)
    if prefs is None:
        prefs = NotificationPref(user_id=user_id)
        session.add(prefs)
    muted = {type_.value for type_ in muted_types}
    prefs.muted_types = [type_.value for type_ in muted_types]
    prefs.email_types = [type_.value for type_ in email_types if type_.value not in muted]
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


async def email_types_by_user(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, frozenset[str]]:
    """Mailer seam: which types each recipient wants EMAILED as they happen.

    Lives beside `muted_types_by_user` because it answers the same kind of
    question, but it returns an entry for EVERY id asked for — absent row means
    `DEFAULT_EMAIL_TYPES`, and a partial dict read with `.get(id, ())` would
    silently mean "email nothing", the exact opposite of the documented default.
    """
    ids = set(user_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(NotificationPref).where(NotificationPref.user_id.in_(ids))
    )
    stored = {prefs.user_id: frozenset(prefs.email_types) for prefs in result.scalars()}
    fallback = frozenset(default_email_type_values())
    return {user_id: stored.get(user_id, fallback) for user_id in ids}


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
