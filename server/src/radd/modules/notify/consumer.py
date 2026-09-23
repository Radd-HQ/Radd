"""The notify outbox consumer: item/comment events → per-user notifications.

Planning is pure (planner.py); this wraps it with lookups (watchers, mention
resolution, permission filtering) and the writes. One transaction per batch;
each event runs in a SAVEPOINT so a bad event is logged and skipped, never
wedging the cursor.

**Transaction ownership (RADD-1047):** whoever OPENS the session commits it.
`run_once` opens one and commits after the batch it drives; `_bootstrap` commits
per batch of the backlog it loops over. `_consume` itself never commits — it is
handed a session and writes into it. Tests exercise it with their rolled-back
fixture session, and a commit here made every fixture row of every such test
permanent in the shared test database (RADD-992: a second file then saw two
senders where it had created one).
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.comments.types import CommentEvent, CommentParentType, CommentVisibility
from radd.modules.comments.visibility import internal_comment_visible
from radd.modules.teams import service as teams
from radd.modules.events import service as events
from radd.modules.events.service import Event
from radd.modules.items import service as items
from radd.modules.items.enums import ItemEvent
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import mentions, pageevents, planner, rules as notify_rules, service
from .audience import actor_name_of, item_audience, own_of, recipient_ids, subject_of
from .audience import item_ref as _ref
from .planner import Plan, PlannedNotification
from .rules import Subject

# `consumer.recipient_ids` is the documented seam (docs/modules.md, spec 72) and
# is re-exported rather than moved, so the name callers already reach for keeps
# working after spec 118 split the recipient set four ways.
__all__ = ["recipient_ids", "run_once"]
from .types import (
    APPROVAL_APPROVED_EVENT,
    APPROVAL_DECLINED_EVENT,
    APPROVAL_REQUESTED_EVENT,
    CONSUMER_NAME,
    PAGE_CREATED_EVENT,
    PAGE_UPDATED_EVENT,
    PARTICIPANT_ADDED_EVENT,
    SLA_BREACHED_EVENT,
    SLA_DUE_SOON_EVENT,
    NotificationType,
)

logger = logging.getLogger(__name__)

# Spec 71 decision events → the notification detail's "action".
_APPROVAL_DECISIONS = {
    APPROVAL_APPROVED_EVENT: "approved",
    APPROVAL_DECLINED_EVENT: "declined",
}

_HANDLED = {
    ItemEvent.CREATED.value,
    ItemEvent.UPDATED.value,
    CommentEvent.CREATED.value,
    SLA_BREACHED_EVENT,
    SLA_DUE_SOON_EVENT,
    APPROVAL_REQUESTED_EVENT,
    APPROVAL_APPROVED_EVENT,
    APPROVAL_DECLINED_EVENT,
    PARTICIPANT_ADDED_EVENT,
    # Spec 118. The wiki's fan-out moved off the save request and onto the
    # stream; adding them here is what makes the bootstrap consider them, and
    # the bootstrap is WATCH-ONLY, so a fresh instance replaying years of page
    # edits writes nothing — `pageevents` contributes no watcher rows either,
    # because `pages.update_page` already writes them on the write path.
    PAGE_CREATED_EVENT,
    PAGE_UPDATED_EVENT,
}

# Page events fan out identically; only the notification kind differs.
_PAGE_EVENT_TYPES = {
    PAGE_CREATED_EVENT: NotificationType.PAGE_CREATED,
    PAGE_UPDATED_EVENT: NotificationType.PAGE_UPDATED,
}

# SLA timer events fan out identically; only the notification type differs.
_SLA_EVENT_TYPES = {
    SLA_BREACHED_EVENT: NotificationType.SLA_BREACH,
    SLA_DUE_SOON_EVENT: NotificationType.SLA_DUE_SOON,
}


async def run_once() -> int:
    async with SessionLocal() as session:
        if not await events.offset_exists(session, CONSUMER_NAME):
            return await _bootstrap(session)
        processed = await _consume(session, watch_only=False)
        await session.commit()
        return processed


async def _consume(session: AsyncSession, *, watch_only: bool) -> int:
    offset = await events.get_offset(session, CONSUMER_NAME)
    batch = await events.read_after(session, offset, settings.notify_batch)
    if not batch:
        return 0
    for event in batch:
        # A bulk import's events are `silent`: nobody is notified about work that
        # happened years ago in another system. The importer sets watchers from the
        # source data explicitly, so skipping these also keeps the watcher graph
        # out of the bootstrap's hands rather than half-derived from imported rows.
        if event.silent or event.event_type not in _HANDLED:
            continue
        try:
            async with session.begin_nested():
                await _handle(session, event, watch_only=watch_only)
        except Exception:
            logger.exception("notify: failed handling event %s (%s)", event.id, event.event_type)
    await events.set_offset(session, CONSUMER_NAME, batch[-1].id)
    return len(batch)


async def _bootstrap(session: AsyncSession) -> int:
    """Very first run: consume the entire historical backlog WATCH-ONLY. This
    backfills the watcher graph from real activity (creators/assignees/commenters
    follow what they touched) without spamming notifications for old events —
    notifications begin from the moment the module first starts."""
    logger.info("notify: first start — backfilling watchers from the event backlog")
    total = 0
    while processed := await _consume(session, watch_only=True):
        # Per batch, not once at the end: a years-long backlog should land
        # progressively, and a crash mid-way must not replay it from zero.
        await session.commit()
        total += processed
    return total


async def _handle(session: AsyncSession, event: Event, *, watch_only: bool) -> None:
    if event.event_type == CommentEvent.CREATED.value:
        await _handle_comment_created(session, event, watch_only=watch_only)
    elif event.event_type in _SLA_EVENT_TYPES:
        if not watch_only:
            await _handle_sla_event(session, event, _SLA_EVENT_TYPES[event.event_type])
    elif event.event_type == APPROVAL_REQUESTED_EVENT or event.event_type in _APPROVAL_DECISIONS:
        if not watch_only:  # approvals never touch the watcher graph (spec 71)
            await _handle_approval_event(session, event)
    elif event.event_type == PARTICIPANT_ADDED_EVENT:
        # The watcher row was written by participants on the WRITE path, so this
        # handler has nothing to contribute to a watch-only bootstrap pass.
        if not watch_only:
            await _handle_participant_added(session, event)
    elif event.event_type in _PAGE_EVENT_TYPES:
        # Same shape, same reason: `pages.update_page` auto-watches the editor
        # itself (RADD-719), so the wiki contributes nothing to the bootstrap.
        if not watch_only:
            await pageevents.handle_page_event(
                session, event, _PAGE_EVENT_TYPES[event.event_type]
            )
    else:
        await _handle_item_event(session, event, watch_only=watch_only)


async def _handle_item_event(session: AsyncSession, event: Event, *, watch_only: bool) -> None:
    payload = event.payload or {}
    item_id = uuid.UUID(event.entity_id)
    created = event.event_type == ItemEvent.CREATED.value
    changed_fields = {change.get("field") for change in payload.get("changes", [])}

    mention_ids: frozenset[uuid.UUID] = frozenset()
    if not watch_only and (created or "description" in changed_fields):
        # Under the ref since RADD-922 (see below) — this read a top-level
        # `description`, so it always scanned "" and a description mention
        # notified nobody.
        mention_ids = await mentions.resolve_mentions(session, _ref(payload).get("description") or "")

    # RADD-817: the row itself, for per-recipient relation gating in _allowed —
    # and, since spec 118, for the item's CURRENT project and team, which is
    # what a subscription is matched against. A deleted item falls back to the
    # payload; the notification then describes something already gone.
    item = await session.get(WorkItem, item_id)
    subject = subject_of(payload, item)
    audience = await item_audience(
        session, item_id, subject, own=own_of(item, payload)
    )

    if created:
        plan = planner.plan_item_created(payload, event.actor_id, mention_ids, audience)
    else:
        plan = planner.plan_item_updated(payload, event.actor_id, audience, mention_ids)

    # RADD-978: RADD-922 nested the item payload under `item` and promoted the
    # project to an `{id, key, name}` ref; this line kept reading a TOP-LEVEL
    # `project_id` that item events had stopped carrying. Every `item.created`
    # and `item.updated` therefore raised KeyError inside the per-event
    # SAVEPOINT, was logged and skipped, and the cursor moved on — so `assigned`,
    # `state_changed` and description `mentioned` reached nobody at all, and the
    # auto-watch graph stopped growing from item activity. Nothing failed
    # loudly; the only symptom was silence. This is what a wire constant with no
    # compiler behind it costs.
    project = await projects_service.get_project(
        session, uuid.UUID(_ref(payload)["project"]["id"])
    )
    await _apply(
        session,
        plan,
        event=event,
        item_id=item_id,
        project=project,
        item_key=_ref(payload).get("key", ""),
        item_title=_ref(payload).get("title", ""),
        watch_only=watch_only,
        item=item,
        subject=subject,
    )


async def _handle_comment_created(
    session: AsyncSession, event: Event, *, watch_only: bool
) -> None:
    """A comment on an ISSUE — or, since RADD-1056, on a PAGE.

    **The bug this branch closes.** `comments` has been polymorphic since
    RADD-717: a comment's parent is an item OR a page, and the event says which
    in `entity_type`. This handler did not look. It read `payload["item"]["id"]`
    unconditionally, and a page comment's `item` subject is NULL by
    construction (the emitter resolves it only for item parents), so every wiki
    comment raised KeyError inside the per-event SAVEPOINT, was logged, and was
    skipped. Page comments produced ZERO notifications for the whole life of the
    feature — including a comment that @-named someone directly. Nothing failed
    loudly, which is how it survived: the wiki fan-out that DID work
    (`page_updated`) made the subsystem look alive.
    """
    payload = event.payload or {}
    if payload.get("entity_type") == CommentParentType.PAGE.value:
        await pageevents.handle_page_comment(session, event, watch_only=watch_only)
        return
    item_id = uuid.UUID(_ref(payload)["id"])
    item = await items.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    mention_ids: frozenset[uuid.UUID] = frozenset()
    if not watch_only:
        mention_ids = await mentions.comment_mentions(session, event, payload)
    subject = subject_of(payload, item)
    audience = await item_audience(
        session, item_id, subject, own=own_of(item, payload)
    )
    plan = planner.plan_comment_created(
        payload, event.actor_id, audience, mention_ids, comment_id=str(event.entity_id)
    )
    await _apply(
        session,
        plan,
        event=event,
        item_id=item_id,
        project=project,
        item_key=_ref(payload).get("key", ""),
        item_title=_ref(payload).get("title", ""),
        watch_only=watch_only,
        item=item,
        subject=subject,
    )


async def _handle_sla_event(
    session: AsyncSession, event: Event, type_: NotificationType
) -> None:
    """sla.breached and (spec 69) sla.due_soon: same fan-out, different type."""
    payload = event.payload or {}
    item_id = uuid.UUID(_ref(payload)["id"])
    item = await items.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    subject = subject_of(payload, item)
    audience = await item_audience(
        session, item_id, subject, own=own_of(item, payload)
    )
    detail = {
        "policy": payload.get("policy_name", ""),
        "kind": payload.get("kind", ""),
        "due_at": payload.get("due_at"),
    }
    if type_ is NotificationType.SLA_DUE_SOON:
        detail["remaining_seconds"] = payload.get("remaining_seconds")
    plan = planner.plan_sla_breached(item.assignee_id, audience, detail, type_)
    await _apply(
        session,
        plan,
        event=event,
        item_id=item_id,
        project=project,
        item_key=_ref(payload).get("key", ""),
        item_title=_ref(payload).get("title", ""),
        item=item,
        subject=subject,
    )


async def _handle_approval_event(session: AsyncSession, event: Event) -> None:
    """Spec 71: requested → each eligible approver (payload-resolved ids — the
    wire-string idiom keeps notify from importing approvals, which loads later);
    approved/declined → the requester."""
    payload = event.payload or {}
    item_id = uuid.UUID(_ref(payload)["id"])
    item = await items.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    if event.event_type == APPROVAL_REQUESTED_EVENT:
        approver_ids = frozenset(
            uuid.UUID(value) for value in payload.get("eligible_user_ids", [])
        )
        plan = planner.plan_approval_requested(payload, event.actor_id, approver_ids)
    else:
        requester = payload.get("requester") or {}
        requester_id = uuid.UUID(requester["id"]) if requester.get("id") else None
        plan = planner.plan_approval_decided(
            payload, event.actor_id, requester_id, _APPROVAL_DECISIONS[event.event_type]
        )
    await _apply(
        session,
        plan,
        event=event,
        item_id=item_id,
        project=project,
        item_key=_ref(payload).get("key", ""),
        item_title=_ref(payload).get("title", ""),
        item=item,
    )


async def _handle_participant_added(session: AsyncSession, event: Event) -> None:
    """RADD-978: tell the person they were shared into an issue.

    The wire-string idiom again — participants loads after notify and may be
    disabled, so this file knows the event by its name and reads its payload,
    never the module. The plan is built FIRST because a team add plans nothing
    and there is then nothing to look anything up for.

    The recipient still passes `_allowed` like every other type. Note what makes
    that pass: the participant ROW already exists (the event is emitted after the
    write), so the Baseline's `item.read@participant` answers the RADD-817
    per-row gate for someone with no other standing in the project — the share
    is what confers the read the notification is checked against.
    """
    payload = event.payload or {}
    plan = planner.plan_participant_added(payload, event.actor_id)
    if not plan.notifications:
        return
    item_id = uuid.UUID(_ref(payload)["id"])
    item = await items.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await _apply(
        session,
        plan,
        event=event,
        item_id=item_id,
        project=project,
        item_key=_ref(payload).get("key", ""),
        item_title=_ref(payload).get("title", ""),
        item=item,
    )


async def _allowed(
    session: AsyncSession,
    planned: PlannedNotification,
    project: Project,
    item: "WorkItem | None" = None,
) -> bool:
    """Recipient must exist, be active, and hold item.read (plus comment.read_internal
    for internal-comment notifications) on the project — and, since RADD-817,
    hold it FOR THIS ROW: a relation-scoped recipient (`item.read@own/@team`)
    must not be told about an issue the list would never show them. This is the
    single delivery choke point, so every notification type inherits it."""
    users = await auth.users_by_ids(session, {planned.user_id})
    user = users.get(planned.user_id)
    if user is None or not user.active:
        return False
    permissions = (await authz.permissions_for_projects(session, user, [project]))[project.id]
    if not authz.holds_base(permissions, Permission.ITEM_READ):
        return False
    if item is not None:
        relations = authz.relations_held(permissions, Permission.ITEM_READ)
        relation_actor = await authz.relation_actor(session, user)
        # async form (RADD-844): a participant reads via a membership TABLE,
        # not an item column — the sync gate would silently drop exactly
        # the recipients participation exists to reach. Spec 121: no @any
        # short-circuit here — the primitive applies the row guard first, so
        # a restricted issue never notifies someone who is not on it.
        if not await authz.relation_holds_row_async(
            session, "item", relations, relation_actor, item
        ):
            return False
    if planned.detail.get("visibility") == CommentVisibility.INTERNAL.value:
        if Permission.COMMENT_READ_INTERNAL not in permissions:
            return False
        # Spec 50: a team-narrowed internal comment only notifies its team members.
        teams_for = {uuid.UUID(t) for t in planned.detail.get("visible_to_teams") or []}
        if not teams_for:
            return True
        has_manage = Permission.PROJECT_MANAGE in permissions
        actor_teams = (
            set() if has_manage else await teams.user_team_ids(session, user.id)
        )
        return internal_comment_visible(
            is_author=False,
            has_read_internal=True,
            has_manage=has_manage,
            comment_teams=teams_for,
            actor_teams=actor_teams,
        )
    return True


async def _apply(
    session: AsyncSession,
    plan: Plan,
    *,
    event: Event,
    item_id: uuid.UUID,
    project: Project,
    item_key: str,
    item_title: str,
    watch_only: bool = False,
    item: "WorkItem | None" = None,
    subject: Subject = Subject(),
) -> None:
    await service.add_watchers(session, item_id, plan.watch)
    if watch_only or not plan.notifications:
        return
    actor_name = await actor_name_of(session, event)
    # RADD-971: the channel decision is enforced INSIDE create_notification, so
    # the types produced outside this consumer obey it too. All this batch does
    # now is prefetch the rules for the whole recipient set — one query instead
    # of one per planned row — which is what keeps the choke point off the N+1.
    rules = await service.rules_by_user(
        session, {planned.user_id for planned in plan.notifications}
    )
    for planned in plan.notifications:
        # The CHANNEL first, the permission second. Both filters drop the same
        # rows whichever order they run in, but `_allowed` costs a permission
        # resolution plus a relation row check PER RECIPIENT, and spec 118
        # multiplied the recipient set by everyone who subscribed to the
        # project. Resolving first means an `off` verdict — which is what a
        # subscriber gets for most kinds — costs a dictionary lookup instead.
        user_rules = rules.get(planned.user_id, notify_rules.EMPTY)
        if service.channels_for(planned.type, user_rules, planned.relation, subject).silent:
            continue
        if not await _allowed(session, planned, project, item):
            continue
        await service.create_notification(
            session,
            user_id=planned.user_id,
            type_=planned.type,
            event_id=event.id,
            item_id=item_id,
            actor_id=event.actor_id,
            payload={
                "item_key": item_key,
                "item_title": item_title,
                "actor_name": actor_name,
                **planned.detail,
            },
            rules=user_rules,
            relation=planned.relation,
            subject=subject,
        )
