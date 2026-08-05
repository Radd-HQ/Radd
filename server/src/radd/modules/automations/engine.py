"""The rules engine: an outbox consumer that matches items via SLQ and applies
actions through the target services as the system actor.

Loop guard (critical): every engine-applied mutation emits its item event with
`actor_id = SYSTEM_ACTOR_ID`. `should_process` skips those, so a rule whose action
sets a field the rule also matches on applies exactly once and never spins.

Best-effort: each action runs inside a SAVEPOINT — a failing action rolls back only
itself, is logged, and the rest continue; the engine never crashes on bad data.

RADD-902: trigger classification, condition matching, and the read-only action
planner (`_plan`/`_Plan`) moved to `planning.py` — the planning-vs-applying
seam the audit named as this file's cleanest cut. Application (`apply_event`/
`_apply_plan`/`_run_rule_actions`), scheduled runs, poll iteration, and the
dry-run preview stay here, and this module re-exports everything `planning.py`
defines under its own name — `from radd.modules.automations.engine import
_plan, condition_matches, should_process, ...` (real callers: `router.py`,
`dispatcher.py`, and several tests) is unaffected.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd import smtp
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth.models import User
from radd.modules.comments import service as comments
from radd.modules.events import service as events
from radd.modules.events.service import Event
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.items import service as items, slq
from radd.modules.items.models import WorkItem
from radd.modules.notify import service as notify_service
from radd.modules.notify.types import NotificationType
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import catalog, conditions, service
from .models import AutomationRule
from .planning import (
    _Plan,
    _cycle_by_name as _cycle_by_name,
    _current_labels as _current_labels,
    _event_facts,
    _is_clear as _is_clear,
    _item_ctx as _item_ctx,
    _manual_facts as _manual_facts,
    _plan as _plan,
    _project_by_key as _project_by_key,
    _project_definitions as _project_definitions,
    _resolve_target_item,
    _state_by_name as _state_by_name,
    _team_by_name as _team_by_name,
    condition_matches as condition_matches,
    is_automation_caused as is_automation_caused,
    should_process as should_process,
)
from .schemas import ActionPreview, RuleTestResult
from .types import (
    CONSUMER_NAME,
    ITEM_ACTIONS,
    SYSTEM_ACTOR_EMAIL,
    SYSTEM_ACTOR_ID,
    SYSTEM_ACTOR_NAME,
    UNIVERSAL_ACTIONS,
    ActionType,
    AutomationEvent,
    AutomationTrigger,
    PlanKind,
)

logger = logging.getLogger(__name__)


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
    if plan.kind is PlanKind.ITEM_UPDATE and plan.item_update is not None and item is not None:
        await items.update_item(session, item.id, plan.item_update, actor=system_user)
    elif plan.kind is PlanKind.COMMENT and plan.comment is not None and item is not None:
        await comments.create_comment(session, item.id, plan.comment, actor=system_user)
    elif plan.kind is PlanKind.CREATE_ITEM and plan.item_create is not None:
        # Emitted item.created carries the system actor — the loop guard skips it.
        await items.create_item(session, plan.item_create, actor=system_user)
    elif plan.kind is PlanKind.HTTP and plan.http is not None:
        url, body, secret = plan.http
        body_bytes = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
            response = await client.post(
                url, content=body_bytes, headers=_signed_headers(body_bytes, secret)
            )
            response.raise_for_status()
    elif plan.kind is PlanKind.EMAIL and plan.email is not None:
        # Sync smtplib off the loop; nothing is emitted — inherently loop-safe.
        to_address, to_name, subject, body = plan.email
        await asyncio.to_thread(smtp.send_message, to_address, subject, body, to_name=to_name)
    elif plan.kind is PlanKind.NOTIFY and plan.notify is not None:
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
                if plan.kind is PlanKind.SKIP:
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
                        resolves=plan.kind is not PlanKind.SKIP,
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
