"""Non-item notification subjects (RADD-1385) — a wiki page today.

The subject arrives on the kernel `NOTIFICATION_SUBJECT` socket; this file is
the mechanism around it, on the item path's seams: `planner` decides who and
what, `rules.resolve` the channels, the provider's `reader_ids` who may hear.
A withdrawn provider means its events notify nobody and its queued rows are not
mailed. Internal comments are gated by `comments.can_read_comment`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import ChoiceRead
from radd.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from radd.kernel import sockets
from radd.kernel.sockets import NotificationSubjectProvider, Socket
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.comments.reading import can_read_comment
from radd.modules.comments.types import CommentVisibility
from radd.modules.events.service import Event

from . import mentions, planner, rules as notify_rules, service
from .audience import actor_name_of, uuid_or_none
from .planner import Audience, Plan
from .rules import Subject
from .types import SUBJECT_ID_KEY, SUBJECT_TYPE_KEY, RuleScope, SubjectRef


def provider(entity_type: str | None) -> NotificationSubjectProvider | None:
    """The live provider for an entity type, or None (never registered, or
    its plugin disabled — the registry forgets both the same way)."""
    return sockets.provider(Socket.NOTIFICATION_SUBJECT, entity_type) if entity_type else None


def _providers() -> list[NotificationSubjectProvider]:
    return list(sockets.providers(Socket.NOTIFICATION_SUBJECT).values())


def provider_for_event(event_type: str) -> NotificationSubjectProvider | None:
    return next((p for p in _providers() if event_type in p.events), None)


def provider_for_scope(scope: RuleScope) -> NotificationSubjectProvider | None:
    return next((p for p in _providers() if p.scope == scope.value), None)


def handles(event_type: str) -> bool:
    return provider_for_event(event_type) is not None


def _subject(subject: NotificationSubjectProvider, ref: SubjectRef) -> Subject:
    """What a subscription can name: the container, in the provider's scope.
    `space` is the only container family `rules.Subject` carries for a
    non-item subject; a provider answering another has no subscriptions."""
    if ref.scope_id is None or subject.scope != RuleScope.SPACE.value:
        return Subject()
    return Subject(space_id=ref.scope_id)


async def _audience(
    session: AsyncSession, subject: NotificationSubjectProvider, ref: SubjectRef
) -> Audience:
    """Watchers (participating) ∪ subscribers to the container. No `own`: nobody
    is assigned a page; its editors watch it."""
    watchers = frozenset(await subject.watcher_ids(session, ref.id))
    container = _subject(subject, ref)
    subscribers = await service.subscriber_ids(session, space_id=container.space_id)
    return Audience(participating=watchers, subscribers=frozenset(subscribers))


async def handle_event(session: AsyncSession, event: Event) -> None:
    """One of a provider's own events (`page.created` → `page_created`, …)."""
    subject = provider_for_event(event.event_type)
    if subject is None:
        return
    ref = await subject.locate(session, event)
    if ref is None:
        return
    audience = await _audience(session, subject, ref)
    plan = planner.plan_subject_event(subject.events[event.event_type], event.actor_id, audience)
    await _apply(session, plan, event=event, subject=subject, ref=ref)


async def handle_comment(
    session: AsyncSession, event: Event, entity_type: str, *, watch_only: bool
) -> None:
    """A comment on a non-item subject (RADD-1056). Nothing is auto-watched
    (`item_watchers` is keyed by item), so the bootstrap has nothing to do here."""
    subject = provider(entity_type)
    if watch_only or subject is None:
        return
    ref = await subject.locate(session, event)
    if ref is None:
        return
    mention_ids = await mentions.comment_mentions(session, event, event.payload or {})
    audience = await _audience(session, subject, ref)
    plan = planner.plan_comment_created(
        event.payload or {}, event.actor_id, audience, mention_ids, follow_actor=False,
        comment_id=str(event.entity_id),
    )
    await _apply(session, plan, event=event, subject=subject, ref=ref)


async def _may_read_comment(session: AsyncSession, comment_id: str | None, user_id: uuid.UUID) -> bool:
    user = (await auth.users_by_ids(session, {user_id})).get(user_id)
    parsed = uuid_or_none(comment_id)
    if user is None or parsed is None:
        return False
    try:
        return await can_read_comment(session, parsed, user)
    except (ForbiddenError, NotFoundError, UnauthorizedError):
        # The parent's own refusal is a "no", like `comments.reading.locate`.
        return False


async def _apply(
    session: AsyncSession,
    plan: Plan,
    *,
    event: Event,
    subject: NotificationSubjectProvider,
    ref: SubjectRef,
) -> None:
    """`consumer._apply`'s shape for a non-item subject: channel first, because
    the provider's read gate (a space role plus an ancestor walk) is per recipient."""
    if not plan.notifications:
        return
    rules = await service.rules_by_user(session, {planned.user_id for planned in plan.notifications})
    container = _subject(subject, ref)
    wanted = [
        planned for planned in plan.notifications
        if not notify_rules.resolve(
            planned.type, rules.get(planned.user_id, notify_rules.EMPTY), planned.relation, container
        ).silent
    ]
    if not wanted:
        return
    readable = await subject.reader_ids(session, ref.id, [planned.user_id for planned in wanted])
    actor_name = await actor_name_of(session, event)
    stamp = {SUBJECT_TYPE_KEY: subject.entity_type, SUBJECT_ID_KEY: str(ref.id)}
    for planned in wanted:
        if planned.user_id not in readable:
            continue
        if planned.detail.get("visibility") == CommentVisibility.INTERNAL.value and not (
            await _may_read_comment(session, planned.detail.get("comment_id"), planned.user_id)
        ):
            continue
        await service.create_notification(
            session,
            user_id=planned.user_id,
            type_=planned.type,
            event_id=event.id,
            # No item: the row carries the subject's own payload instead, which
            # is why `notifications.item_id` has always been nullable.
            item_id=None,
            actor_id=event.actor_id,
            payload={"actor_name": actor_name, **ref.payload, **stamp, **planned.detail},
            rules=rules.get(planned.user_id),
            relation=planned.relation,
            subject=container,
        )


async def readable(session: AsyncSession, payload: dict, user: User) -> bool:
    """The mail loops' re-check: may this person STILL read the row's subject?
    No provider (or no stamped subject) means nobody vouches for it."""
    subject = provider(payload.get(SUBJECT_TYPE_KEY))
    subject_id = uuid_or_none(payload.get(SUBJECT_ID_KEY))
    if subject is None or subject_id is None:
        return False
    return user.id in await subject.reader_ids(session, subject_id, [user.id])


async def scope_options(
    session: AsyncSession, actor: User, scope: RuleScope, *, q: str, limit: int, offset: int,
    exclude: list[str],
) -> tuple[list[ChoiceRead], int]:
    """The subscription picker for a provider-backed scope; empty without one —
    an instance with no wiki has no spaces, which is the answer, not a gap."""
    subject = provider_for_scope(scope)
    if subject is None:
        return [], 0
    return await subject.scope_options(
        session, actor, q=q, limit=limit, offset=offset, exclude=exclude
    )


async def scope_names(
    session: AsyncSession, actor: User, scope: RuleScope, ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Of these containers, the ones this actor may NAME, by name."""
    subject = provider_for_scope(scope)
    if subject is None or not ids:
        return {}
    return await subject.scope_names(session, actor, ids)
