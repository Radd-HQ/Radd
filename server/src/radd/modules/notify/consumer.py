"""The notify outbox consumer: item/comment events → per-user notifications.

Planning is pure (planner.py); this wraps it with lookups (watchers, mention
resolution, permission filtering) and the writes. One transaction per batch;
each event runs in a SAVEPOINT so a bad event is logged and skipped, never
wedging the cursor.

Whoever OPENS the session commits it (RADD-1047): `_consume` never commits,
which is what lets tests drive it inside their rolled-back fixture session.
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

from . import kinds, mentions, planner, rules as notify_rules, service, subjects
from .audience import actor_name_of, item_audience, own_of, subject_of
from .audience import item_ref as _ref
from .planner import Plan, PlannedNotification
from .rules import Subject
from .types import (
    APPROVAL_APPROVED_EVENT,
    APPROVAL_DECLINED_EVENT,
    APPROVAL_REQUESTED_EVENT,
    CONSUMER_NAME,
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
}

# SLA timer events fan out identically; only the notification type differs.
_SLA_EVENT_TYPES = {
    SLA_BREACHED_EVENT: NotificationType.SLA_BREACH,
    SLA_DUE_SOON_EVENT: NotificationType.SLA_DUE_SOON,
}


def handles(event_type: str) -> bool:
    """The core families, contributed kinds (RADD-1326), and every LIVE
    subject provider's events (RADD-1385)."""
    return (
        event_type in _HANDLED
        or event_type in kinds.contributed_events()
        or subjects.handles(event_type)
    )


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
        # An import's events are `silent`: nobody is told about old work, and the
        # importer sets watchers from the source data itself.
        if event.silent or not handles(event.event_type):
            continue
        try:
            async with session.begin_nested():
                await _handle(session, event, watch_only=watch_only)
        except Exception:
            logger.exception("notify: failed handling event %s (%s)", event.id, event.event_type)
    await events.set_offset(session, CONSUMER_NAME, batch[-1].id)
    return len(batch)


async def _bootstrap(session: AsyncSession) -> int:
    """Very first run: consume the whole backlog WATCH-ONLY — the watcher graph
    backfills from real activity; notifications begin from now."""
    logger.info("notify: first start — backfilling watchers from the event backlog")
    total = 0
    while processed := await _consume(session, watch_only=True):
        # Per batch: a crash mid-way must not replay the backlog from zero.
        await session.commit()
        total += processed
    return total


async def _handle(session: AsyncSession, event: Event, *, watch_only: bool) -> None:
    with events.derived_from(event, silent=watch_only):
        await _handle_derived(session, event, watch_only=watch_only)


async def _handle_derived(session: AsyncSession, event: Event, *, watch_only: bool) -> None:
    if not watch_only:
        # Contributed kinds (RADD-1326) and non-item subjects (RADD-1385) only
        # notify: neither follows anything, so the bootstrap skips them.
        for spec in kinds.contributed_for(event.event_type):
            await _handle_contributed(session, event, spec)
        await subjects.handle_event(session, event)
    if event.event_type not in _HANDLED:
        return
    if event.event_type == CommentEvent.CREATED.value:
        await _handle_comment_created(session, event, watch_only=watch_only)
    elif event.event_type in _SLA_EVENT_TYPES:
        if not watch_only:
            await _handle_sla_event(session, event, _SLA_EVENT_TYPES[event.event_type])
    elif event.event_type == APPROVAL_REQUESTED_EVENT or event.event_type in _APPROVAL_DECISIONS:
        if not watch_only:  # approvals never touch the watcher graph (spec 71)
            await _handle_approval_event(session, event)
    elif event.event_type == PARTICIPANT_ADDED_EVENT:
        if not watch_only:  # participants auto-watched on the write path
            await _handle_participant_added(session, event)
    else:
        await _handle_item_event(session, event, watch_only=watch_only)


async def _handle_item_event(session: AsyncSession, event: Event, *, watch_only: bool) -> None:
    payload = event.payload or {}
    item_id = uuid.UUID(event.entity_id)
    created = event.event_type == ItemEvent.CREATED.value
    changed_fields = {change.get("field") for change in payload.get("changes", [])}

    mention_ids: frozenset[uuid.UUID] = frozenset()
    if not watch_only and (created or "description" in changed_fields):
        mention_ids = await mentions.resolve_mentions(session, _ref(payload).get("description") or "")

    # The row: for `_allowed`'s per-row gate (RADD-817) and the item's CURRENT
    # project/team, which subscriptions match. A deleted item falls back to the payload.
    item = await session.get(WorkItem, item_id)
    subject = subject_of(payload, item)
    audience = await item_audience(
        session, item_id, subject, own=own_of(item, payload)
    )

    if created:
        plan = planner.plan_item_created(payload, event.actor_id, mention_ids, audience)
    else:
        plan = planner.plan_item_updated(payload, event.actor_id, audience, mention_ids)

    project = await projects_service.get_project(
        session, uuid.UUID(_ref(payload)["project"]["id"])
    )
    await _apply(
        session,
        plan,
        event=event,
        item_id=item_id,
        project=project,
        watch_only=watch_only,
        item=item,
        subject=subject,
    )


async def _item_context(
    session: AsyncSession, payload: dict
) -> tuple[uuid.UUID, WorkItem, Project]:
    """The item an item-scoped event's canonical ref names, and its project."""
    item_id = uuid.UUID(_ref(payload)["id"])
    item = await items.require_item(session, item_id)
    return item_id, item, await projects_service.get_project(session, item.project_id)


async def _handle_comment_created(
    session: AsyncSession, event: Event, *, watch_only: bool
) -> None:
    """A comment on an issue; a page comment goes to its subject provider
    (RADD-1056: branch on `entity_type` — a page comment has no `item`)."""
    payload = event.payload or {}
    parent = payload.get("entity_type") or CommentParentType.ITEM.value
    if parent != CommentParentType.ITEM.value:
        # No live provider (its plugin disabled) means nobody hears it.
        await subjects.handle_comment(session, event, parent, watch_only=watch_only)
        return
    item_id, item, project = await _item_context(session, payload)
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
        watch_only=watch_only,
        item=item,
        subject=subject,
    )


async def _handle_sla_event(
    session: AsyncSession, event: Event, type_: NotificationType
) -> None:
    """sla.breached and (spec 69) sla.due_soon: same fan-out, different type."""
    payload = event.payload or {}
    item_id, item, project = await _item_context(session, payload)
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
        session, plan, event=event, item_id=item_id, project=project, item=item, subject=subject
    )


async def _handle_approval_event(session: AsyncSession, event: Event) -> None:
    """Spec 71: requested → each eligible approver (payload-resolved ids — the
    wire-string idiom keeps notify from importing approvals, which loads later);
    approved/declined → the requester."""
    payload = event.payload or {}
    item_id, item, project = await _item_context(session, payload)
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
    await _apply(session, plan, event=event, item_id=item_id, project=project, item=item)


async def _handle_participant_added(session: AsyncSession, event: Event) -> None:
    """RADD-978: tell the person they were shared into an issue; a team add
    plans nothing, so nothing is looked up. They pass `_allowed` via the
    Baseline's `item.read@participant` — the participant row already exists, so
    the share confers the read it is checked against."""
    payload = event.payload or {}
    plan = planner.plan_participant_added(payload, event.actor_id)
    if not plan.notifications:
        return
    item_id, item, project = await _item_context(session, payload)
    await _apply(session, plan, event=event, item_id=item_id, project=project, item=item)


async def _handle_contributed(session: AsyncSession, event: Event, spec) -> None:
    """A plugin's notification kind (RADD-1326), through the same choke points
    as every core kind: the channel matrix and, for an issue, `_allowed`. The
    plugin says WHO (`recipients`) and WHAT (`render`); it never writes a row.
    Personal by default; the actor is never told about their own action."""
    payload = event.payload or {}
    recipients = {uuid.UUID(str(uid)) for uid in (await spec.recipients(session, event) or ())}
    if event.actor_id is not None:
        recipients.discard(event.actor_id)
    if not recipients:
        return
    actor_name = await actor_name_of(session, event)
    text = (spec.render(payload, actor_name) if spec.render is not None else None) or {}
    detail = {
        "headline": str(text.get("headline") or spec.label),
        "link": text.get("link"),
        "subject": text.get("subject"),
    }
    ref = payload.get("item") if isinstance(payload.get("item"), dict) else None
    if ref and ref.get("id"):
        item_id = uuid.UUID(str(ref["id"]))
        item = await session.get(WorkItem, item_id)
        if item is None:
            return
        project = await projects_service.get_project(session, item.project_id)
        plan = Plan()
        for user_id in sorted(recipients, key=str):
            plan.notifications.append(PlannedNotification(user_id, spec.key, detail))
        await _apply(
            session, plan, event=event, item_id=item_id, project=project, item=item,
            item_key=str(ref.get("key") or ""), item_title=str(ref.get("title") or ""),
        )
        return
    rules = await service.rules_by_user(session, recipients)
    for user_id in sorted(recipients, key=str):
        await service.create_notification(
            session,
            user_id=user_id,
            type_=spec.key,
            event_id=event.id,
            item_id=None,
            actor_id=event.actor_id,
            payload={"actor_name": actor_name, **detail},
            rules=rules.get(user_id, notify_rules.EMPTY),
        )


async def _allowed(
    session: AsyncSession,
    planned: PlannedNotification,
    project: Project,
    item: "WorkItem | None" = None,
) -> bool:
    """The single delivery choke point: an active recipient holding item.read
    (plus comment.read_internal for an internal comment) on the project, and
    FOR THIS ROW (RADD-817) — `item.read@own/@team` must not hear about an issue
    the list would never show them."""
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
        # The async form (RADD-844): a participant reads via a membership TABLE,
        # which the sync gate would silently drop. No @any short-circuit (spec
        # 121): the row guard runs first, so a restricted issue stays restricted.
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
    watch_only: bool = False,
    item: "WorkItem | None" = None,
    subject: Subject = Subject(),
    item_key: str | None = None,
    item_title: str | None = None,
) -> None:
    """Watch, then write each planned row that survives the channel and `_allowed`.
    Key and title come from the event's canonical item ref unless given."""
    await service.add_watchers(session, item_id, plan.watch)
    if watch_only or not plan.notifications:
        return
    ref = _ref(event.payload or {})
    item_key = ref.get("key", "") if item_key is None else item_key
    item_title = ref.get("title", "") if item_title is None else item_title
    actor_name = await actor_name_of(session, event)
    # One rules query for the whole recipient set; `create_notification` still
    # enforces the channel itself (RADD-971), so this only avoids an N+1.
    rules = await service.rules_by_user(
        session, {planned.user_id for planned in plan.notifications}
    )
    for planned in plan.notifications:
        # The CHANNEL first: same rows either way, but `_allowed` costs a
        # permission resolution per recipient and an `off` verdict — what most
        # subscribers get — costs a dict lookup.
        user_rules = rules.get(planned.user_id, notify_rules.EMPTY)
        if notify_rules.resolve(planned.type, user_rules, planned.relation, subject).silent:
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
