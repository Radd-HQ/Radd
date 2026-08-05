import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.items import slq

from radd import schedule as schedule_math
from radd.clock import utcnow
from .models import AutomationRule, AutomationScheduleState
from .schemas import RuleCreate, RuleRead, RuleUpdate
from .types import (
    SYSTEM_ACTOR_ID,
    AutomationEntity,
    AutomationEvent,
    AutomationTrigger,
)


async def _scope_definitions(session: AsyncSession) -> dict[str, FieldDefinition]:
    """key -> definition over the whole field registry (oldest wins on dup keys) —
    the scope a rule's condition is validated against on write."""
    by_key: dict[str, FieldDefinition] = {}
    for definition in await fields.list_fields(session):
        by_key.setdefault(definition.key, definition)
    return by_key


async def _validate_condition(session: AsyncSession, condition_slq: str) -> None:
    """Parse + compile the condition against the field registry. Any problem raises
    SlqError, which the items module's handler renders as 422 {detail, position}."""
    text = condition_slq.strip()
    if not text:
        return
    await slq.compile_query(
        session,
        slq.parse(text),
        definitions_by_key=await _scope_definitions(session),
        current_user_id=SYSTEM_ACTOR_ID,
        project_id=None,
    )


def _serialize_actions(data: RuleCreate | RuleUpdate) -> list[dict]:
    return [action.model_dump(mode="json") for action in data.actions or []]



def _check_schedule_consistency(rule: AutomationRule) -> None:
    """Spec 69 invariants after a write: `schedule` present iff the trigger is
    the schedule sentinel, and scheduled rules carry no event conditions
    (there is no event). Raised as 409 per the form-error idiom."""
    scheduled = rule.trigger == AutomationTrigger.SCHEDULE
    if scheduled and rule.schedule is None:
        raise ConflictError(AutomationEntity.RULE, reason="a scheduled rule needs a schedule")
    if not scheduled and rule.schedule is not None:
        raise ConflictError(
            AutomationEntity.RULE, reason="only schedule-triggered rules take a schedule"
        )
    if scheduled and rule.event_conditions is not None:
        raise ConflictError(
            AutomationEntity.RULE,
            reason="a scheduled rule cannot have event conditions (there is no event)",
        )


async def _sync_schedule_state(session: AsyncSession, rule: AutomationRule) -> None:
    """(Re)compute the rule's automation_schedule_state row: enabled scheduled
    rules get a fresh next_run_at; everything else drops the row."""
    state = await session.get(AutomationScheduleState, rule.id)
    active = rule.trigger == AutomationTrigger.SCHEDULE and rule.enabled
    if not active:
        if state is not None:
            await session.delete(state)
            await session.flush()
        return
    next_run_at = schedule_math.next_run(rule.schedule, utcnow(), settings.scheduler_tz)
    if state is None:
        session.add(AutomationScheduleState(rule_id=rule.id, next_run_at=next_run_at))
    else:
        state.next_run_at = next_run_at
    await session.flush()


async def create_rule(
    session: AsyncSession, data: RuleCreate, actor_id: uuid.UUID | None = None
) -> AutomationRule:
    await _validate_condition(session, data.condition_slq)
    rule = AutomationRule(
        name=data.name,
        enabled=data.enabled,
        trigger=data.trigger,
        event_conditions=(
            data.event_conditions.model_dump(mode="json") if data.event_conditions else None
        ),
        condition_slq=data.condition_slq,
        actions=_serialize_actions(data),
        position=data.position,
        schedule=(
            data.schedule.model_dump(mode="json", exclude_none=True) if data.schedule else None
        ),
    )
    _check_schedule_consistency(rule)
    session.add(rule)
    await session.flush()
    await _sync_schedule_state(session, rule)
    await _emit(session, AutomationEvent.CREATED, rule, actor_id)
    return rule


async def update_rule(
    session: AsyncSession, rule_id: uuid.UUID, data: RuleUpdate, actor_id: uuid.UUID | None = None
) -> AutomationRule:
    rule = await get_rule(session, rule_id)
    if data.name is not None:
        rule.name = data.name
    if data.enabled is not None:
        rule.enabled = data.enabled
    if data.trigger is not None:
        rule.trigger = data.trigger
    if "event_conditions" in data.model_fields_set:
        rule.event_conditions = (
            data.event_conditions.model_dump(mode="json") if data.event_conditions else None
        )
    if "condition_slq" in data.model_fields_set:
        condition = data.condition_slq or ""
        await _validate_condition(session, condition)
        rule.condition_slq = condition
    if data.actions is not None:
        rule.actions = _serialize_actions(data)
    if data.position is not None:
        rule.position = data.position
    if "schedule" in data.model_fields_set:
        rule.schedule = (
            data.schedule.model_dump(mode="json", exclude_none=True) if data.schedule else None
        )
    _check_schedule_consistency(rule)
    await session.flush()
    await _sync_schedule_state(session, rule)
    await _emit(session, AutomationEvent.UPDATED, rule, actor_id)
    return rule


async def get_rule(session: AsyncSession, rule_id: uuid.UUID) -> AutomationRule:
    rule = await session.get(AutomationRule, rule_id)
    if rule is None:
        raise NotFoundError(AutomationEntity.RULE, rule_id)
    return rule


async def list_rules(session: AsyncSession) -> list[AutomationRule]:
    result = await session.execute(
        select(AutomationRule).order_by(AutomationRule.position, AutomationRule.created_at)
    )
    return list(result.scalars())


async def delete_rule(
    session: AsyncSession, rule_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    rule = await get_rule(session, rule_id)
    await _emit(session, AutomationEvent.DELETED, rule, actor_id)
    await session.delete(rule)


async def rules_for_trigger(
    session: AsyncSession, trigger: str
) -> list[AutomationRule]:
    """Enabled rules whose trigger (event type or "manual") matches, in
    evaluation order (engine seam)."""
    result = await session.execute(
        select(AutomationRule)
        .where(
            AutomationRule.enabled.is_(True),
            AutomationRule.trigger == trigger,
        )
        .order_by(AutomationRule.position, AutomationRule.created_at)
    )
    return list(result.scalars())


async def schedule_states(
    session: AsyncSession, rule_ids: list[uuid.UUID]
) -> dict[uuid.UUID, AutomationScheduleState]:
    """Scheduler bookkeeping rows by rule id (spec 69) — RuleRead hydration seam."""
    if not rule_ids:
        return {}
    result = await session.execute(
        select(AutomationScheduleState).where(AutomationScheduleState.rule_id.in_(rule_ids))
    )
    return {state.rule_id: state for state in result.scalars()}


async def rule_reads(session: AsyncSession, rules: list[AutomationRule]) -> list[RuleRead]:
    """RuleRead payloads with next/last-run stamps batch-hydrated from
    automation_schedule_state (None for event/manual rules)."""
    states = await schedule_states(session, [rule.id for rule in rules])
    reads: list[RuleRead] = []
    for rule in rules:
        state = states.get(rule.id)
        reads.append(
            RuleRead.model_validate(rule).model_copy(
                update={
                    "next_run_at": state.next_run_at if state else None,
                    "last_run_at": state.last_run_at if state else None,
                }
            )
        )
    return reads


async def _emit(
    session: AsyncSession,
    event_type: AutomationEvent,
    rule: AutomationRule,
    actor_id: uuid.UUID | None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=AutomationEntity.RULE,
        entity_id=rule.id,
        actor_id=actor_id,
        payload={"name": rule.name, "trigger": rule.trigger, "enabled": rule.enabled},
    )
