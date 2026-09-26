import uuid
from collections.abc import Iterable, Sequence
from typing import TypeGuard

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.auth.types import UserSource
from radd.modules.events import service as events

from . import rules as rules_policy
from .kinds import every_kind
from .models import ItemWatcher, Notification, NotificationPref, NotificationRule
from .rules import Relation, RuleRow, RuleSet, Subject
from .types import (
    SUBSCRIPTION_SCOPES,
    SYSTEM_ACTOR_ID,
    Channel,
    NotificationType,
    NotifyEntity,
    NotifyEvent,
    RuleScope,
)
from radd.clock import utcnow



# --- watchers ---


async def add_watchers(
    session: AsyncSession,
    item_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID],
    *,
    auto: bool = True,
    actor_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Idempotent bulk follow; returns who was NEWLY added and emits
    `item.watched` (payload `auto`) for them only (RADD-1320)."""
    rows = [{"item_id": item_id, "user_id": user_id} for user_id in set(user_ids)]
    if not rows:
        return []
    inserted = await session.execute(
        pg_insert(ItemWatcher).values(rows).on_conflict_do_nothing().returning(ItemWatcher.user_id)
    )
    added = list(inserted.scalars())
    for user_id in added:
        await events.emit(
            session,
            event_type=NotifyEvent.ITEM_WATCHED,
            entity_type=NotifyEntity.WATCHER,
            entity_id=item_id,
            actor_id=actor_id if actor_id is not None else (None if auto else user_id),
            subjects={"item": item_id, "user": user_id},
            payload={"auto": auto},
        )
    return added


async def watch(
    session: AsyncSession,
    item_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Manual follow — idempotent; `item.watched` (auto=false) only on first add."""
    await add_watchers(session, item_id, [user_id], auto=False)


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
        subjects={"item": item_id, "user": user_id},
    )


async def watcher_ids(session: AsyncSession, item_id: uuid.UUID) -> list[uuid.UUID]:
    result = await session.execute(
        select(ItemWatcher.user_id).where(ItemWatcher.item_id == item_id)
    )
    return list(result.scalars())


# --- who has a mailbox ---


def mailable_user(user: User | None) -> TypeGuard[User]:
    """Is there a PERSON's mailbox behind this account? (RADD-996)

    No for inactive, address-less, `UserSource.SERVICE`/`PRINCIPAL` accounts and
    the system actor. A property of the ACCOUNT, so both loops stamp and move on
    rather than retry (a delivery failure is the retrying case, `retry.py`).
    Inbox rows for service accounts are left alone.
    """
    if user is None or not user.active or not user.email:
        return False
    if user.id == SYSTEM_ACTOR_ID:
        return False
    return user.source not in (UserSource.SERVICE.value, UserSource.PRINCIPAL.value)


# --- notifications ---


async def create_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    type_: NotificationType | str,
    event_id: int | None,
    item_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    payload: dict,
    rules: RuleSet | None = None,
    relation: Relation = rules_policy.OWN,
    subject: Subject = Subject(),
) -> Notification | None:
    """Write one notification for one recipient — unless their rules say `off`.

    The ONE write seam every producer calls (RADD-971), so a new producer
    inherits the channel policy. Pass `relation` + `subject` when the connection
    is known; a caller that simply picked a recipient gets own-scope semantics.
    `rules` is an optional prefetch (`rules_by_user`). Returns None when `off`.
    """
    # RADD-996: nobody reads the system actor's inbox. This also makes its
    # historical auto-watch rows on mailed-in tickets inert, so they stay.
    if user_id == SYSTEM_ACTOR_ID:
        return None
    if rules is None:
        rules = (await rules_by_user(session, [user_id])).get(user_id, rules_policy.EMPTY)
    verdict = rules_policy.resolve(type_, rules, relation, subject)
    if verdict.silent:
        return None
    notification = Notification(
        user_id=user_id,
        event_id=event_id,
        type=str(type_),
        item_id=item_id,
        actor_id=actor_id,
        payload=payload,
        # Spec 118: stamped, not re-derived per tick — only the write knows the relation.
        inbox=verdict.inbox,
        email=verdict.email,
    )
    session.add(notification)
    await session.flush()
    # Realtime pushes this for live bells; `inbox` tells an email-only row apart.
    await events.emit(
        session,
        event_type=NotifyEvent.NOTIFICATION_CREATED,
        entity_type=NotifyEntity.NOTIFICATION,
        entity_id=notification.id,
        actor_id=actor_id,
        payload={
            "user_id": str(user_id),
            "type": str(type_),
            "item_id": str(item_id) if item_id else None,
            "inbox": verdict.inbox,
        },
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
    """The INBOX: `inbox IS TRUE` — an email-only row is not in the list."""
    stmt = select(Notification).where(
        Notification.user_id == user_id, Notification.inbox.is_(True)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    result = await session.execute(
        stmt.order_by(Notification.created_at.desc(), Notification.id).limit(limit).offset(offset)
    )
    return list(result.scalars())


async def unread_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    """The badge — the same filter as the list it labels."""
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.inbox.is_(True),
        )
    )
    return int(result.scalar_one())


#: Marking read is an INBOX act: the mailer skips read rows, so without this
#: filter "mark all read" would cancel pending email-only sends.
_INBOX_ROW = Notification.inbox.is_(True)


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
            _INBOX_ROW,
        )
        .values(read_at=utcnow())
    )


async def mark_all_read(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None), _INBOX_ROW)
        .values(read_at=utcnow())
    )


# --- per-user rules (no rows = `rules.default_matrix()`) ---


async def get_prefs(session: AsyncSession, user_id: uuid.UUID) -> NotificationPref | None:
    return await session.get(NotificationPref, user_id)


async def set_digest(
    session: AsyncSession, user_id: uuid.UUID, *, email_digest: bool
) -> NotificationPref:
    prefs = await session.get(NotificationPref, user_id)
    if prefs is None:
        prefs = NotificationPref(user_id=user_id)
        session.add(prefs)
    prefs.email_digest = email_digest
    await session.flush()
    return prefs


def clean_channels(channels: dict[str, str]) -> dict[str, str]:
    """Drop (kind, channel) pairs this version does not know — core and
    contributed kinds (RADD-1326). The API already 422s them; this guards
    non-HTTP callers of `set_rules`, and reads of rows whose plugin is gone."""
    known = set(every_kind())
    cleaned: dict[str, str] = {}
    for kind, channel in channels.items():
        if kind not in known:
            continue
        try:
            cleaned[kind] = Channel(channel).value
        except ValueError:
            continue
    return cleaned


async def set_rules(
    session: AsyncSession,
    user_id: uuid.UUID,
    rows: Sequence[tuple[RuleScope, uuid.UUID | None, dict[str, str]]],
) -> list[NotificationRule]:
    """Full replace; returns the NORMALISED rows. A subscription scope must name
    a target and a relationship scope must not — violators are dropped, as are
    empty `channels` maps (no opinion = no row = defaults)."""
    await session.execute(
        delete(NotificationRule).where(NotificationRule.user_id == user_id)
    )
    stored: list[NotificationRule] = []
    seen: set[tuple[str, uuid.UUID | None]] = set()
    for scope, scope_id, channels in rows:
        wants_target = scope in SUBSCRIPTION_SCOPES
        if wants_target != (scope_id is not None):
            continue
        key = (scope.value, scope_id)
        if key in seen:
            continue
        cleaned = clean_channels(channels)
        if not cleaned:
            continue
        seen.add(key)
        row = NotificationRule(
            user_id=user_id, scope=scope.value, scope_id=scope_id, channels=cleaned
        )
        session.add(row)
        stored.append(row)
    await session.flush()
    return stored


async def list_rules(session: AsyncSession, user_id: uuid.UUID) -> list[NotificationRule]:
    result = await session.execute(
        select(NotificationRule)
        .where(NotificationRule.user_id == user_id)
        .order_by(NotificationRule.scope, NotificationRule.scope_id)
    )
    return list(result.scalars())


def scope_of(row: NotificationRule) -> RuleScope | None:
    """The row's scope, or None for one this version does not know (it reaches nobody)."""
    try:
        return RuleScope(row.scope)
    except ValueError:
        return None


def _rule_row(row: NotificationRule) -> RuleRow | None:
    scope = scope_of(row)
    if scope is None:
        return None
    return RuleRow(scope=scope, scope_id=row.scope_id, channels=row.channels or {})


async def rules_by_user(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RuleSet]:
    """Every recipient's rules in one query — an entry for EVERY id asked (an
    empty `RuleSet` = defaults), so no call site guesses a `.get` fallback."""
    ids = set(user_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(NotificationRule).where(NotificationRule.user_id.in_(ids))
    )
    collected: dict[uuid.UUID, list[RuleRow]] = {user_id: [] for user_id in ids}
    for row in result.scalars():
        parsed = _rule_row(row)
        if parsed is not None:
            collected[row.user_id].append(parsed)
    return {user_id: RuleSet.of(rows) for user_id, rows in collected.items()}


async def subscriber_ids(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    space_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    """Who subscribed to any of these targets — one indexed query per event.
    Channels are NOT consulted here (that would be a second resolver in SQL);
    `resolve` drops the `off` ones."""
    targets = [
        (RuleScope.PROJECT, project_id),
        (RuleScope.SPACE, space_id),
        (RuleScope.TEAM, team_id),
    ]
    clauses = [
        (NotificationRule.scope == scope.value) & (NotificationRule.scope_id == target)
        for scope, target in targets
        if target is not None
    ]
    if not clauses:
        return set()
    result = await session.execute(
        select(NotificationRule.user_id).where(or_(*clauses)).distinct()
    )
    return set(result.scalars())


async def team_scope_user_ids(session: AsyncSession) -> set[uuid.UUID]:
    """Everyone with a my-teams rule — intersected with the team's CURRENT members at fan-out."""
    result = await session.execute(
        select(NotificationRule.user_id)
        .where(NotificationRule.scope == RuleScope.TEAMS.value)
        .distinct()
    )
    return set(result.scalars())


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
