"""Wiki fan-out, behind the same consumer as everything else (spec 118).

RADD-719 delivered page notifications SYNCHRONOUSLY, from inside the request
that saved the page, and said so: page edits are rare, the recipient list is
small, "and a consumer would mean a second delivery path to keep correct for a
volume that does not need one". The volume was never the argument that mattered
— it WAS a second delivery path, and it drifted exactly where a second path
drifts. It knew about page watchers and nothing else, it applied no read gate,
and it could not be given a space subscription without growing a second copy of
the resolver. `page.created` notified nobody at all.

So this file is the wiki's half of `consumer.py`, on the same three seams:
`planner` decides who and what, `rules.resolve` decides the channels, and a
per-recipient gate decides whether they may hear it. Only the gate differs, and
it has to: a page's visibility is a space role PLUS every restriction on the
ancestor path (RADD-948), which is the wiki's answer to give, not notify's to
reimplement.

**Everything about `pages` is reached deferred and feature-detected.** It loads
AFTER notify and is a disableable plugin, so an instance with the wiki off must
degrade to "no page notifications" rather than to an ImportError in a background
loop. The event's own payload carries the page and space REFS (the kernel writes
them from `emit(subjects=…)`), so the only thing this file actually needs the
module for is the read gate and the watcher list.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.comments.types import CommentVisibility
from radd.modules.comments.visibility import internal_comment_visible
from radd.modules.events.service import Event
from radd.modules.teams import service as teams

from . import mentions, planner, rules as notify_rules, service
from .audience import actor_name_of
from .planner import Audience, Plan, PlannedNotification
from .rules import Subject
from .types import PAGE_SPACE_SUBJECT, PAGE_SUBJECT, NotificationType

logger = logging.getLogger(__name__)


def _pages():
    """The wiki's public seam, or None when the plugin is not loaded."""
    try:
        from radd.modules.pages import refs as pages_refs
    except ImportError:
        return None
    return pages_refs


def _page_of(payload: dict) -> dict:
    return payload.get(PAGE_SUBJECT) or {}


def _space_of(payload: dict) -> dict:
    return payload.get(PAGE_SPACE_SUBJECT) or {}


def _page_payload(page: dict, space: dict) -> dict:
    """The stored notification payload for anything about a page.

    The same five keys RADD-719 wrote, and for its reason: an inbox row renders
    and links from the payload alone, resolved at write time, so a later rename
    cannot make the entry lie about what it told you at the time.
    """
    return {
        "page_id": page.get("id"),
        "page_number": page.get("number"),
        "page_slug": page.get("slug"),
        "space_slug": space.get("slug"),
        "title": page.get("title"),
        "version": page.get("version"),
    }


async def _page_audience(
    session: AsyncSession, page_id: uuid.UUID, space_id: uuid.UUID | None
) -> Audience:
    """Watchers (participating) ∪ subscribers to the page's SPACE.

    A page has no `own`: nobody is assigned one, and treating its creator as an
    owner would mean the person who wrote a runbook two years ago inherits a
    column they never chose. They watch it — which is what `participating`
    says — because editing auto-watches.
    """
    pages = _pages()
    watchers = frozenset(await pages.page_watcher_ids(session, page_id)) if pages else frozenset()
    subscribers = await service.subscriber_ids(session, space_id=space_id)
    return Audience(participating=watchers, subscribers=frozenset(subscribers))


async def _internal_visible(
    session: AsyncSession,
    planned: PlannedNotification,
    space_id: uuid.UUID | None,
) -> bool:
    """The internal-comment filter, resolved in the page's SPACE.

    The space is the scope the WRITE gate used (`pages.comments_binding`
    resolves `comment.write` there, and `_check_internal` tests the same
    space-scoped set), so it is the scope this has to agree with. Page comment
    READS still resolve the atom globally, a pre-spec-791 leftover in
    `comments.list_comments` that is out of this spec's scope — noted here so
    the disagreement is recorded rather than discovered.
    """
    if planned.detail.get("visibility") != CommentVisibility.INTERNAL.value:
        return True
    if space_id is None:
        return False
    users = await auth.users_by_ids(session, {planned.user_id})
    user = users.get(planned.user_id)
    if user is None:
        return False
    permissions = await authz.effective_permissions(session, user, space_id=space_id)
    if Permission.COMMENT_READ_INTERNAL not in permissions:
        return False
    teams_for = {uuid.UUID(t) for t in planned.detail.get("visible_to_teams") or []}
    if not teams_for:
        return True
    has_manage = Permission.PAGE_MANAGE in permissions
    actor_teams = set() if has_manage else await teams.user_team_ids(session, user.id)
    return internal_comment_visible(
        is_author=False,
        has_read_internal=True,
        has_manage=has_manage,
        comment_teams=teams_for,
        actor_teams=actor_teams,
    )


async def _apply_page(
    session: AsyncSession,
    plan: Plan,
    *,
    event: Event,
    page_id: uuid.UUID,
    space_id: uuid.UUID | None,
    payload: dict,
) -> None:
    """Resolve, gate, write — `consumer._apply`'s shape for a page.

    Channel first, permission second, for the same reason: the read gate is a
    space-permission resolution plus an ancestor walk per recipient, and a
    subscriber whose verdict is `off` should not cost either.
    """
    if not plan.notifications:
        return
    pages = _pages()
    if pages is None:
        return  # the wiki is not loaded; there is nothing to check them against
    rules = await service.rules_by_user(
        session, {planned.user_id for planned in plan.notifications}
    )
    subject = Subject(space_id=space_id)
    wanted: list[PlannedNotification] = []
    for planned in plan.notifications:
        user_rules = rules.get(planned.user_id, notify_rules.EMPTY)
        if service.channels_for(planned.type, user_rules, planned.relation, subject).silent:
            continue
        wanted.append(planned)
    if not wanted:
        return
    readable = await pages.readable_page_ids_for_users(
        session, page_id, [planned.user_id for planned in wanted]
    )
    actor_name = await actor_name_of(session, event)
    for planned in wanted:
        if planned.user_id not in readable:
            continue
        if not await _internal_visible(session, planned, space_id):
            continue
        await service.create_notification(
            session,
            user_id=planned.user_id,
            type_=planned.type,
            event_id=event.id,
            # No item: a page notification carries page context instead, which is
            # why `notifications.item_id` has always been nullable.
            item_id=None,
            actor_id=event.actor_id,
            payload={"actor_name": actor_name, **payload, **planned.detail},
            rules=rules.get(planned.user_id),
            relation=planned.relation,
            subject=subject,
        )


async def handle_page_event(
    session: AsyncSession, event: Event, type_: NotificationType
) -> None:
    """`page.created` → PAGE_CREATED, `page.updated` → PAGE_UPDATED."""
    payload = event.payload or {}
    page, space = _page_of(payload), _space_of(payload)
    page_id = _uuid(page.get("id")) or _uuid(event.entity_id)
    if page_id is None:
        return
    space_id = _uuid(space.get("id"))
    audience = await _page_audience(session, page_id, space_id)
    plan = planner.plan_page_event(type_, event.actor_id, audience)
    await _apply_page(
        session,
        plan,
        event=event,
        page_id=page_id,
        space_id=space_id,
        payload=_page_payload(page, space),
    )


async def handle_page_comment(
    session: AsyncSession, event: Event, *, watch_only: bool
) -> None:
    """A comment on a page (RADD-1056 — this produced nothing at all before).

    The comment event carries `entity_id` (the page) and no page ref: `comments`
    is polymorphic and resolves an `item` subject only for item parents, which
    is exactly the None the old handler crashed on. So the page and its space
    are looked up through the wiki's seam, once.

    Nothing is auto-watched. `item_watchers` is keyed by item and a page has no
    row there; commenting on a page does not subscribe you to it, which is a
    smaller promise than the issue path makes and the only one the table can
    keep.
    """
    if watch_only:
        return  # nothing to backfill: page comments write no watcher rows
    pages = _pages()
    if pages is None:
        return
    payload = event.payload or {}
    page_id = _uuid(payload.get("entity_id"))
    if page_id is None:
        return
    page = await pages.page_ref(session, page_id) or {}
    space = await pages.space_of_page_ref(session, page_id) or {}
    space_id = _uuid(space.get("id"))
    mention_ids = await mentions.comment_mentions(session, event, payload)
    audience = await _page_audience(session, page_id, space_id)
    plan = planner.plan_comment_created(
        payload, event.actor_id, audience, mention_ids, follow_actor=False
    )
    await _apply_page(
        session,
        plan,
        event=event,
        page_id=page_id,
        space_id=space_id,
        payload=_page_payload(page, space),
    )


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except (ValueError, TypeError, AttributeError):
        return None
