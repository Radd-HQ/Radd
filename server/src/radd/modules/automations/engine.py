"""The rules engine: an outbox consumer that matches items via SLQ and applies
actions through the target services as the system actor.

Loop guard (critical): every engine-applied mutation emits its item event with
`actor_id = SYSTEM_ACTOR_ID`. `should_process` skips those, so a rule whose action
sets a field the rule also matches on applies exactly once and never spins.

Best-effort: each action runs inside a SAVEPOINT — a failing action rolls back only
itself, is logged, and the rest continue; the engine never crashes on bad data.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd import smtp
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.comments import service as comments
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentVisibility
from radd.modules.cycles import service as cycles_service
from radd.modules.events import service as events
from radd.modules.events.service import Event
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.items import service as items, slq
from radd.modules.items.enums import ItemEntity, Priority
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.notify import service as notify_service
from radd.modules.notify.types import NotificationType
from radd.modules.releases import service as releases_service
from radd.modules.teams import service as teams_service
from radd.modules.workflow import service as workflow
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import catalog, conditions, service
from .email_action import resolve_recipient
from .models import AutomationRule
from .schemas import ActionPreview, RuleTestResult
from .templating import render_template
from .types import (
    CLEAR_VALUE,
    CONSUMER_NAME,
    ITEM_ACTIONS,
    SYSTEM_ACTOR_EMAIL,
    SYSTEM_ACTOR_ID,
    SYSTEM_ACTOR_NAME,
    UNIVERSAL_ACTIONS,
    ActionType,
    AutomationEvent,
    AutomationTrigger,
)

logger = logging.getLogger(__name__)


# --- loop guard + trigger classification ---


def is_automation_caused(event: Event) -> bool:
    """True if this event was emitted by an engine-applied mutation (the loop guard)."""
    return event.actor_id == SYSTEM_ACTOR_ID


def should_process(event: Event) -> bool:
    """A human/API event on a subscribable type — never an automation-caused one.
    EXCEPTION (spec 69): the scheduler's synthetic `automation.scheduled` event is
    system-emitted by design, so it bypasses the loop-guard skip — loop safety
    holds because the item events a scheduled run emits carry the system actor,
    which this predicate still rejects on the EVENT-rule path.

    `silent` events (a bulk import, `events.quiet()`) never match: a rule that
    assigns on create or transitions on a field change would otherwise fire once
    per imported issue and rewrite the history being imported. Checked ahead of
    the scheduled-event exception — an import is silent whatever it emits."""
    if event.silent:
        return False
    if event.event_type == AutomationEvent.SCHEDULED.value:
        return True
    return event.event_type in catalog.TRIGGERS and not is_automation_caused(event)


async def _resolve_target_item(session: AsyncSession, event: Event) -> WorkItem | None:
    """The item a rule's SLQ + actions apply to: the event's entity when it IS an
    item, else the payload's `item_id` (comments, worklogs, attachments, links —
    the stream-wide convention). None for itemless events (cycles, docs, …)."""
    item_id: uuid.UUID | None = None
    if event.entity_type == ItemEntity.ITEM.value:
        item_id = uuid.UUID(event.entity_id)
    else:
        raw = (event.payload or {}).get("item_id")
        if raw:
            try:
                item_id = uuid.UUID(str(raw))
            except ValueError:
                return None
    return None if item_id is None else await session.get(WorkItem, item_id)


async def _event_facts(session: AsyncSession, event: Event) -> conditions.EventFacts:
    actor = (
        await session.get(User, event.actor_id) if event.actor_id is not None else None
    )
    return conditions.EventFacts(
        event_type=event.event_type,
        actor_id=str(event.actor_id) if event.actor_id else None,
        actor_email=actor.email if actor else None,
        actor_name=actor.name if actor else None,
        payload=event.payload or {},
    )


# --- condition matching (reuses the SLQ compiler, filtered to the one item) ---


async def _project_definitions(
    session: AsyncSession, project: Project
) -> dict[str, FieldDefinition]:
    by_key: dict[str, FieldDefinition] = {}
    for definition in await fields.definitions_for_project(session, project):
        by_key.setdefault(definition.key, definition)
    return by_key


async def condition_matches(
    session: AsyncSession, condition_slq: str, item: WorkItem, project: Project
) -> bool:
    """Does the item satisfy the rule's condition? Empty condition = always. Reuses the
    SLQ compiler and runs the compiled WHERE guarded to this single item id."""
    text = (condition_slq or "").strip()
    if not text:
        return True
    compiled = await slq.compile_query(
        session,
        slq.parse(text),
        definitions_by_key=await _project_definitions(session, project),
        current_user_id=SYSTEM_ACTOR_ID,
        project_id=project.id,
    )
    stmt = select(WorkItem.id).where(WorkItem.id == item.id)
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)
    return await session.scalar(stmt) is not None


# --- action planning (shared by apply + dry-run preview; resolution does no writes) ---


@dataclass
class _Plan:
    kind: str  # "item_update" | "comment" | "create_item" | "http" | "notify" | "email" | "skip"
    detail: str
    item_update: ItemUpdate | None = None
    comment: CommentCreate | None = None
    item_create: ItemCreate | None = None
    # (url, json_body, headers) for send_webhook / post_chat.
    http: tuple[str, dict[str, Any], dict[str, str]] | None = None
    # (user_id, message) for notify_user.
    notify: tuple[uuid.UUID, str] | None = None
    # (to_address, to_name, subject, body) for send_email (spec 66).
    email: tuple[str, str, str, str] | None = None


def _manual_facts() -> conditions.EventFacts:
    """Stand-in facts for manual runs / previews — templates degrade verbatim."""
    return conditions.EventFacts(
        event_type="manual", actor_id=None, actor_email=None, actor_name=None, payload={}
    )


def _item_ctx(item: WorkItem | None, project: Project | None) -> dict[str, Any] | None:
    if item is None or project is None:
        return None
    return {"key": f"{project.key}-{item.number}", "title": item.title, "id": str(item.id)}


def _is_clear(value: str) -> bool:
    return value.strip().lower() == CLEAR_VALUE


async def _state_by_name(session: AsyncSession, project_id: uuid.UUID, name: str):
    for state in await workflow.list_states(session, project_id):
        if state.name == name:
            return state
    return None


async def _team_by_name(session: AsyncSession, name: str):
    for team in await teams_service.list_teams(session):
        if team.name == name:
            return team
    return None


async def _cycle_by_name(session: AsyncSession, name: str):
    for cycle in await cycles_service.list_cycles(session):
        if cycle.name == name:
            return cycle
    return None


async def _current_labels(session: AsyncSession, item: WorkItem, system_user: User) -> list[str]:
    read = await items.get_item(session, item.id, actor=system_user)
    return list(read.labels)


async def _project_by_key(session: AsyncSession, key: str) -> Project | None:
    for project in await projects_service.list_projects(session):
        if project.key.casefold() == key.strip().casefold():
            return project
    return None


async def _plan(
    session: AsyncSession,
    action: dict,
    item: WorkItem | None,
    project: Project | None,
    system_user: User,
    *,
    facts: conditions.EventFacts,
    rule_name: str,
) -> _Plan:
    """Resolve one stored action — read-only. Returns the work to perform, or a
    'skip' plan when a named target no longer resolves (logged, not fatal).
    Item actions require `item`/`project` (the caller guarantees it); universal
    actions (spec 58b) render their `{{token}}` templates from `facts`."""
    action_type = ActionType(action["type"])
    params = action["params"]
    ictx = _item_ctx(item, project)
    match action_type:
        case ActionType.CREATE_ITEM:
            target = await _project_by_key(session, params["project"])
            if target is None:
                return _Plan("skip", f"create_item: no project {params['project']!r}")
            create = ItemCreate(
                project_id=target.id,
                title=render_template(params["title"], facts, ictx),
                description=render_template(params.get("description", ""), facts, ictx),
                priority=Priority(params["priority"]) if params.get("priority") else Priority.NORMAL,
            )
            return _Plan(
                "create_item", f"create_item in {target.key}: {create.title!r}", item_create=create
            )
        case ActionType.SEND_WEBHOOK:
            body = {
                "rule": rule_name,
                "event_type": facts.event_type,
                "actor": {
                    "id": facts.actor_id,
                    "email": facts.actor_email,
                    "name": facts.actor_name,
                },
                "item": ictx,
                "payload": facts.payload,
            }
            return _Plan(
                "http",
                f"send_webhook -> {params['url']}",
                http=(params["url"], body, params.get("secret", "")),
            )
        case ActionType.POST_CHAT:
            message = render_template(params["message"], facts, ictx)
            return _Plan(
                "http",
                f"post_chat -> {params['webhook_url']}",
                http=(params["webhook_url"], {"text": message}, ""),
            )
        case ActionType.NOTIFY_USER:
            email = params["user"]
            user = await auth.get_user_by_email(session, email)
            if user is None:
                return _Plan("skip", f"notify_user: no user {email!r}")
            message = render_template(params["message"], facts, ictx)
            return _Plan("notify", f"notify_user {email}", notify=(user.id, message))
        case ActionType.SEND_EMAIL:
            if not settings.smtp_host:
                return _Plan("skip", "send_email: smtp not configured (smtp_host empty)")
            recipient = await resolve_recipient(session, params["to"], item)
            if recipient is None:
                return _Plan("skip", f"send_email: no recipient resolves for {params['to']!r}")
            address, name = recipient
            return _Plan(
                "email",
                f"send_email -> {address}",
                email=(
                    address,
                    name,
                    render_template(params["subject"], facts, ictx),
                    render_template(params["body"], facts, ictx),
                ),
            )
        case ActionType.SET_STATE:
            name = params["state"]
            state = await _state_by_name(session, project.id, name)
            if state is None:
                return _Plan("skip", f"set_state: no state {name!r} in {project.key}")
            return _Plan("item_update", f"set_state -> {name!r}", ItemUpdate(state_id=state.id))
        case ActionType.SET_PRIORITY:
            priority = Priority(params["priority"])
            return _Plan(
                "item_update", f"set_priority -> {priority.value}", ItemUpdate(priority=priority)
            )
        case ActionType.SET_ASSIGNEE:
            email = params["assignee"]
            if _is_clear(email):
                return _Plan("item_update", "set_assignee -> none", ItemUpdate(assignee_id=None))
            user = await auth.get_user_by_email(session, email)
            if user is None:
                return _Plan("skip", f"set_assignee: no user {email!r}")
            return _Plan("item_update", f"set_assignee -> {email}", ItemUpdate(assignee_id=user.id))
        case ActionType.SET_TEAM:
            name = params["team"]
            if _is_clear(name):
                return _Plan("item_update", "set_team -> none", ItemUpdate(team_id=None))
            team = await _team_by_name(session, name)
            if team is None:
                return _Plan("skip", f"set_team: no team {name!r}")
            return _Plan("item_update", f"set_team -> {name!r}", ItemUpdate(team_id=team.id))
        case ActionType.ADD_LABEL:
            label = params["label"]
            current = await _current_labels(session, item, system_user)
            new = current if label in current else [*current, label]
            note = " (already present)" if label in current else ""
            return _Plan("item_update", f"add_label {label!r}{note}", ItemUpdate(labels=new))
        case ActionType.REMOVE_LABEL:
            label = params["label"]
            current = await _current_labels(session, item, system_user)
            if label not in current:
                return _Plan("skip", f"remove_label: {label!r} not on item")
            new = [name for name in current if name != label]
            return _Plan("item_update", f"remove_label {label!r}", ItemUpdate(labels=new))
        case ActionType.SET_CYCLE:
            name = params["cycle"]
            if _is_clear(name):
                return _Plan("item_update", "set_cycle -> none", ItemUpdate(cycle_id=None))
            cycle = await _cycle_by_name(session, name)
            if cycle is None:
                return _Plan("skip", f"set_cycle: no cycle {name!r}")
            return _Plan("item_update", f"set_cycle -> {name!r}", ItemUpdate(cycle_id=cycle.id))
        case ActionType.SET_RELEASE:
            version = params["release"]
            if _is_clear(version):
                return _Plan("item_update", "set_release -> none", ItemUpdate(release_id=None))
            release = await releases_service.resolve_release(session, project.id, version)
            if release is None:
                return _Plan("skip", f"set_release: no release {version!r} in {project.key}")
            return _Plan(
                "item_update", f"set_release -> {version!r}", ItemUpdate(release_id=release.id)
            )
        case ActionType.SET_CUSTOM_FIELD:
            key, value = params["key"], params["value"]
            return _Plan(
                "item_update", f"set_custom_field {key!r}", ItemUpdate(custom_fields={key: value})
            )
        case ActionType.ADD_COMMENT:
            visibility = CommentVisibility(params.get("visibility", CommentVisibility.PUBLIC.value))
            comment = CommentCreate(body=params["body"], visibility=visibility)
            return _Plan("comment", f"add_comment ({visibility.value})", comment=comment)
    return _Plan("skip", f"unknown action {action_type}")  # pragma: no cover


def _signed_headers(body_bytes: bytes, secret: str) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    if secret:
        headers["x-radd-signature"] = hmac.new(
            secret.encode(), body_bytes, hashlib.sha256
        ).hexdigest()
    return headers


async def _apply_plan(
    session: AsyncSession,
    plan: _Plan,
    item: WorkItem | None,
    system_user: User,
    *,
    rule_name: str,
) -> None:
    if plan.kind == "item_update" and plan.item_update is not None and item is not None:
        await items.update_item(session, item.id, plan.item_update, actor=system_user)
    elif plan.kind == "comment" and plan.comment is not None and item is not None:
        await comments.create_comment(session, item.id, plan.comment, actor=system_user)
    elif plan.kind == "create_item" and plan.item_create is not None:
        # Emitted item.created carries the system actor — the loop guard skips it.
        await items.create_item(session, plan.item_create, actor=system_user)
    elif plan.kind == "http" and plan.http is not None:
        url, body, secret = plan.http
        body_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
            response = await client.post(
                url, content=body_bytes, headers=_signed_headers(body_bytes, secret)
            )
            response.raise_for_status()
    elif plan.kind == "email" and plan.email is not None:
        # Sync smtplib off the loop; nothing is emitted — inherently loop-safe.
        to_address, to_name, subject, body = plan.email
        await asyncio.to_thread(smtp.send_message, to_address, subject, body, to_name=to_name)
    elif plan.kind == "notify" and plan.notify is not None:
        user_id, message = plan.notify
        await notify_service.create_notification(
            session,
            user_id=user_id,
            type_=NotificationType.AUTOMATION,
            event_id=None,
            item_id=item.id if item is not None else None,
            actor_id=SYSTEM_ACTOR_ID,
            payload={"message": message, "rule": rule_name},
        )


# --- per-event application (one transaction per event; the caller commits) ---


async def apply_event(session: AsyncSession, event: Event) -> None:
    """Run every matching rule's actions for one event, best-effort. Any catalog
    trigger is subscribable (spec 58): the rule's event conditions gate on the
    event itself; when a target item resolves, the SLQ condition and the item
    actions apply to it — a matching rule on an itemless event logs and skips
    its actions (they are all item-bound today)."""
    if not should_process(event):
        return
    if event.event_type == AutomationEvent.SCHEDULED.value:  # spec 69 scheduler path
        await apply_scheduled(session, event)
        return
    rules = await service.rules_for_trigger(session, event.event_type)
    if not rules:
        return
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    if system_user is None:
        logger.error(
            "automations: system actor %s missing — run the migration; skipping event %s",
            SYSTEM_ACTOR_ID,
            event.id,
        )
        return
    item = await _resolve_target_item(session, event)
    if item is None and catalog.TRIGGERS[event.event_type].item_scoped:
        return  # item vanished before the engine caught up
    project = (
        await projects_service.get_project(session, item.project_id) if item else None
    )
    facts = await _event_facts(session, event)
    for rule in rules:
        try:
            if not conditions.matches(facts, rule.event_conditions):
                continue
            if item is not None and project is not None:
                if not await condition_matches(session, rule.condition_slq, item, project):
                    continue
            elif (rule.condition_slq or "").strip():
                continue  # SLQ needs an item; an itemless event can't satisfy it
        except Exception:
            logger.exception("automations: condition eval failed for rule %s", rule.id)
            continue
        await _run_rule_actions(session, rule, item, project, system_user, facts=facts)


async def _run_rule_actions(
    session,
    rule,
    item: WorkItem | None,
    project: Project | None,
    system_user,
    *,
    facts: conditions.EventFacts,
    only: frozenset[ActionType] | None = None,
) -> None:
    """Execute one rule's actions, best-effort per action. Item actions need the
    event's target item (skip-logged without one, spec 58b); universal actions
    (create_item/send_webhook/post_chat/notify_user) always run. `only` narrows
    the run to a subset of action types (the spec-69 scheduled path executes
    item actions per matching item, then universal actions exactly once)."""
    for action in rule.actions:
        try:
            if only is not None and ActionType(action["type"]) not in only:
                continue
            if ActionType(action["type"]) in ITEM_ACTIONS and item is None:
                logger.info(
                    "automations: rule %s: item action %s skipped — %s has no target item",
                    rule.id,
                    action.get("type"),
                    facts.event_type,
                )
                continue
            async with session.begin_nested():
                plan = await _plan(
                    session,
                    action,
                    item,
                    project,
                    system_user,
                    facts=facts,
                    rule_name=rule.name,
                )
                if plan.kind == "skip":
                    logger.info("automations: rule %s %s", rule.id, plan.detail)
                else:
                    await _apply_plan(
                        session,
                        plan,
                        item,
                        system_user,
                        rule_name=rule.name,
                    )
        except Exception:
            logger.exception(
                "automations: action %s of rule %s failed (item %s)",
                action.get("type"),
                rule.id,
                item.id if item is not None else "—",
            )


# --- scheduled runs (spec 69): the `automation.scheduled` consumer path ---


def _scheduled_facts(event: Event, matched_count: int | None = None) -> conditions.EventFacts:
    """Facts for a scheduled run's templates: the system actor + the synthetic
    payload, with `{{matched_count}}` merged in for the universal-action pass."""
    payload = dict(event.payload or {})
    if matched_count is not None:
        payload["matched_count"] = matched_count
    return conditions.EventFacts(
        event_type=event.event_type,
        actor_id=str(SYSTEM_ACTOR_ID),
        actor_email=SYSTEM_ACTOR_EMAIL,
        actor_name=SYSTEM_ACTOR_NAME,
        payload=payload,
    )


async def _all_definitions(session: AsyncSession) -> dict[str, FieldDefinition]:
    """key -> definition over the whole field registry (oldest wins on dups) —
    the scope a scheduled rule's SLQ compiles against (no single project)."""
    by_key: dict[str, FieldDefinition] = {}
    for definition in await fields.list_fields(session):
        by_key.setdefault(definition.key, definition)
    return by_key


async def _scheduled_matches(session: AsyncSession, rule: AutomationRule) -> list[uuid.UUID]:
    """Active items matching the rule's SLQ condition, ordered by rank, capped at
    settings.automation_schedule_max_items (truncation logged)."""
    compiled = await slq.compile_query(
        session,
        slq.parse(rule.condition_slq.strip()),
        definitions_by_key=await _all_definitions(session),
        current_user_id=SYSTEM_ACTOR_ID,
        project_id=None,
    )
    cap = settings.automation_schedule_max_items
    stmt = (
        select(WorkItem.id)
        .where(WorkItem.archived_at.is_(None))
        .order_by(WorkItem.rank)
        .limit(cap + 1)
    )
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)
    ids = list((await session.execute(stmt)).scalars())
    if len(ids) > cap:
        logger.info(
            "automations: scheduled rule %s matched over %d items — run truncated",
            rule.id,
            cap,
        )
        ids = ids[:cap]
    return ids


async def apply_scheduled(session: AsyncSession, event: Event) -> None:
    """Execute the payload rule of one `automation.scheduled` event (spec 69).
    Empty condition_slq -> universal actions once, itemless (item actions
    skip+log). Non-empty -> ITEM actions per matching item (rank order, capped),
    then universal actions once with `{{matched_count}}` available. Every
    resulting item event carries the SYSTEM actor, so event rules still skip
    them (the loop guard holds)."""
    payload = event.payload or {}
    try:
        rule_id = uuid.UUID(str(payload.get("rule_id")))
    except ValueError:
        logger.warning("automations: scheduled event %s has no valid rule_id", event.id)
        return
    rule = await session.get(AutomationRule, rule_id)
    if rule is None or not rule.enabled or rule.trigger != AutomationTrigger.SCHEDULE:
        return  # deleted / disabled / re-triggered between emit and consume
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    if system_user is None:
        logger.error(
            "automations: system actor %s missing — run the migration; skipping event %s",
            SYSTEM_ACTOR_ID,
            event.id,
        )
        return
    if not (rule.condition_slq or "").strip():
        # No SLQ: nothing item-shaped to iterate — one itemless pass (item
        # actions skip+log, exactly like itemless event triggers).
        await _run_rule_actions(
            session, rule, None, None, system_user, facts=_scheduled_facts(event, 0)
        )
        return
    try:
        item_ids = await _scheduled_matches(session, rule)
    except Exception:
        logger.exception("automations: scheduled rule %s condition failed to compile", rule.id)
        return
    facts = _scheduled_facts(event)
    projects: dict[uuid.UUID, Project] = {}
    for item_id in item_ids:
        item = await session.get(WorkItem, item_id)
        if item is None:
            continue
        if item.project_id not in projects:
            projects[item.project_id] = await projects_service.get_project(
                session, item.project_id
            )
        await _run_rule_actions(
            session,
            rule,
            item,
            projects[item.project_id],
            system_user,
            facts=facts,
            only=ITEM_ACTIONS,
        )
    await _run_rule_actions(
        session,
        rule,
        None,
        None,
        system_user,
        facts=_scheduled_facts(event, len(item_ids)),
        only=UNIVERSAL_ACTIONS,
    )


async def run_manual(session: AsyncSession, rule: AutomationRule, item_id: uuid.UUID) -> bool:
    """Run a MANUAL rule on one item, on demand (the editor `/` quick-action seam,
    POST /automations/{id}/run). The rule's SLQ condition is still respected — returns
    False when the item doesn't match, True when the actions were executed."""
    item = await items.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    if system_user is None:
        raise RuntimeError("automations: system actor missing — run the migration")
    if not await condition_matches(session, rule.condition_slq, item, project):
        return False
    await _run_rule_actions(session, rule, item, project, system_user, facts=_manual_facts())
    return True


# --- poll iteration (mirrors webhooks.service.fanout_events; one txn per event) ---


async def run_once(session_factory=SessionLocal) -> int:
    """Consume one batch: apply each triggering event in its own transaction, then advance
    the cursor. Returns the number of events consumed."""
    async with session_factory() as session:
        offset = await events.get_offset(session, CONSUMER_NAME)
        batch = await events.read_after(session, offset, settings.automation_batch)
    if not batch:
        return 0
    for event in batch:
        if not should_process(event):
            continue
        try:
            async with session_factory() as session:
                await apply_event(session, event)
                await session.commit()
        except Exception:
            logger.exception("automations: failed processing event %s", event.id)
    async with session_factory() as session:
        await events.set_offset(session, CONSUMER_NAME, batch[-1].id)
        await session.commit()
    return len(batch)


# --- dry-run preview (POST /automations/{id}/test) ---


async def preview(
    session: AsyncSession, rule: AutomationRule, item_id: uuid.UUID
) -> RuleTestResult:
    """Which actions WOULD apply to `item_id`, without writing anything."""
    item = await items.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    system_user = await session.get(User, SYSTEM_ACTOR_ID)
    matched = await condition_matches(session, rule.condition_slq, item, project)
    previews: list[ActionPreview] = []
    if matched:
        for action in rule.actions:
            try:
                plan = await _plan(
                    session,
                    action,
                    item,
                    project,
                    system_user,
                    facts=_manual_facts(),
                    rule_name=rule.name,
                )
                previews.append(
                    ActionPreview(
                        type=ActionType(action["type"]),
                        params=action["params"],
                        resolves=plan.kind != "skip",
                        detail=plan.detail,
                    )
                )
            except Exception as exc:  # malformed stored action — surface, don't crash
                previews.append(
                    ActionPreview(
                        type=ActionType(action["type"]),
                        params=action["params"],
                        resolves=False,
                        detail=f"error: {exc}",
                    )
                )
    return RuleTestResult(
        rule_id=rule.id, item_id=item.id, matched=matched, would_apply=previews
    )
