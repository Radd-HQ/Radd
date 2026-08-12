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
from .models import ItemWatcher, Notification, NotificationPref, NotificationRule
from .rules import Relation, RuleRow, RuleSet, Subject, Verdict
from .types import (
    SUBSCRIPTION_SCOPES,
    SYSTEM_ACTOR_ID,
    NotificationType,
    NotifyEntity,
    NotifyEvent,
    RuleScope,
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
    rules: RuleSet | None = None,
    relation: Relation = rules_policy.OWN,
    subject: Subject = Subject(),
) -> Notification | None:
    """Write one notification for one recipient — unless their rules say `off`.

    The channel decision lives here because this is the one function every
    producer calls (RADD-971). It used to be a mute list checked in the outbox
    consumer alone, so the two types created by a direct call — `automation`
    (automations/engine.py) and `page_updated` (pages/watchers.py) — never saw a
    preference at all. Deciding at the WRITE means a new producer inherits the
    policy instead of re-implementing it.

    Spec 118 widened what is decided here from "is this type muted" to "which
    channels does this person receive this kind through, given how they are
    connected to it". A caller that knows the connection passes `relation` +
    `subject`; one that has simply picked a recipient (an automation rule's
    `notify_user`) passes neither and gets own-scope semantics, which is what
    directly addressing someone means.

    `rules` is an optional PREFETCH for callers fanning out to a known recipient
    set (`rules_by_user` resolves the whole set in one query, so the loop costs
    nothing per row). `None` means "look it up" — a caller that forgets it is
    slower, never wrong. Returns None when the verdict was `off`.
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
    if rules is None:
        rules = (await rules_by_user(session, [user_id])).get(user_id, rules_policy.EMPTY)
    verdict = rules_policy.resolve(type_, rules, relation, subject)
    if verdict.silent:
        return None
    notification = Notification(
        user_id=user_id,
        event_id=event_id,
        type=type_.value,
        item_id=item_id,
        actor_id=actor_id,
        payload=payload,
        # Spec 118: the verdict is STAMPED, not re-derived. The mailer used to
        # ask each row's recipient "do you email this type" on every tick, which
        # is the only question a row could answer once it had forgotten which
        # relation produced it — so a project subscriber and an assignee got the
        # same answer about the same kind, whatever their matrix said.
        inbox=verdict.inbox,
        email=verdict.email,
    )
    session.add(notification)
    await session.flush()
    # The realtime module (spec 27) pushes this so bells update live. `inbox`
    # rides along so a consumer can tell an email-only row from one that changes
    # a badge — the badge count itself filters on the column, so an extra
    # refetch would be harmless, but a receiver should not have to guess.
    await events.emit(
        session,
        event_type=NotifyEvent.NOTIFICATION_CREATED,
        entity_type=NotifyEntity.NOTIFICATION,
        entity_id=notification.id,
        actor_id=actor_id,
        payload={
            "user_id": str(user_id),
            "type": type_.value,
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
    """The INBOX — `inbox IS TRUE`, since spec 118 made the two channels
    independent. An email-only row is a real row with a real recipient; it just
    is not something they asked to see in a list."""
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
    """The badge. Same filter as the list it labels — a count that included
    email-only rows would show a number the inbox cannot account for, which is
    the one thing a badge must never do."""
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


#: Marking read is an INBOX act, and the filter is load-bearing (spec 118).
#:
#: `mailer._pending` selects unread rows — an email is not worth sending about
#: something you have already opened. An email-ONLY row can never be opened,
#: because it is not in the list; without this, "mark all read" would silently
#: cancel every pending email-only send, which is the exact opposite of what the
#: person clicking it asked for.
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


# --- per-user rules (no rows = the DEFAULT_MATRIX, i.e. RADD-686's behaviour) ---


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


def _clean_channels(channels: dict[str, str]) -> dict[str, str]:
    """Keep only (kind, channel) pairs both enums recognise.

    Normalising rather than 422ing, on `set_prefs`'s old reasoning: an unknown
    kind is a client that is ahead of or behind this server, and storing it
    would leave a key the resolver silently ignores forever. Dropping it is the
    same answer, said where the caller can see it in the response.
    """
    from .types import Channel  # local: the enum, not the policy

    cleaned: dict[str, str] = {}
    for kind, channel in channels.items():
        try:
            cleaned[NotificationType(kind).value] = Channel(channel).value
        except ValueError:
            continue
    return cleaned


async def set_rules(
    session: AsyncSession,
    user_id: uuid.UUID,
    rows: Sequence[tuple[RuleScope, uuid.UUID | None, dict[str, str]]],
) -> list[NotificationRule]:
    """Full replace of one person's rule set. Returns the NORMALISED rows.

    Full replace rather than per-row PATCH because the matrix is edited as a
    whole and a partial update has no way to express "I removed a subscription".
    The normalisation is where the model's one invariant is enforced: a
    subscription scope MUST name a target and a relationship scope must not, so
    a row that gets it wrong is dropped rather than stored as something the
    resolver could never match.

    An EMPTY `channels` map means "no opinion anywhere", which is the same thing
    as having no row — so those are dropped too, and a user who resets every
    cell ends up back at zero rows and therefore at the documented defaults.
    """
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
        cleaned = _clean_channels(channels)
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


def _rule_row(row: NotificationRule) -> RuleRow | None:
    try:
        scope = RuleScope(row.scope)
    except ValueError:
        return None  # a scope this version does not know: not a scope that reaches anyone
    return RuleRow(scope=scope, scope_id=row.scope_id, channels=row.channels or {})


async def rules_by_user(
    session: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RuleSet]:
    """THE prefetch seam: every recipient's rules in one query.

    Returns an entry for EVERY id asked about — an absent entry would read as
    `.get(id, ...)` at the call site and the fallback there is easy to get
    backwards (RADD-686 learned this the hard way with `email_types_by_user`).
    An empty `RuleSet` is the honest value for someone who has never saved
    anything, and `resolve` turns it into the documented defaults.
    """
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
    """Who SUBSCRIBED to any of these targets (spec 118's fan-out widening).

    One indexed query per event over `ix_notification_rules_target`, not one per
    scope: an item event can match a project subscription and a team
    subscription at once, and three round trips per event would be three times
    the cost for the same answer.

    A row's channels are NOT consulted here. Narrowing by "…and the row turns
    something on" would be a second copy of the resolver written in SQL, and the
    two would drift the first time precedence changed. The planner adds these
    people, `resolve` drops the ones whose rules say `off`, and that decision
    stays in one place.
    """
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
    """Everyone with a `teams` (my-teams) rule at all.

    The my-teams column cannot be looked up by target — its rows carry no
    `scope_id`, because "my teams" is whatever they are today. So fan-out
    intersects this set with the item team's CURRENT members instead, which is
    both the correct live semantics and far cheaper than the other direction
    (every team of every candidate recipient).
    """
    result = await session.execute(
        select(NotificationRule.user_id)
        .where(NotificationRule.scope == RuleScope.TEAMS.value)
        .distinct()
    )
    return set(result.scalars())


def channels_for(
    kind: NotificationType,
    rules: RuleSet,
    relation: Relation = rules_policy.OWN,
    subject: Subject = Subject(),
) -> Verdict:
    """The resolver, re-exported so callers outside this module have one door."""
    return rules_policy.resolve(kind, rules, relation, subject)


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
