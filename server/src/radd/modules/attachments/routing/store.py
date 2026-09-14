"""Routing-rule CRUD (spec 102). Configs are validated against the rule type's
`config_model` on every write — the chain evaluator tolerates stale configs by
falling through, but the admin UI should never be able to save one."""

import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.kernel import changes
from radd.modules.events import service as events

from ..models import StorageRule
from ..types import AttachmentEntity, AttachmentEvent, RuleType
from .engine import handler_for, ordered_rules

__all__ = ["ordered_rules", "get_rule", "create_rule", "update_rule", "delete_rule", "reorder"]


class RuleConfigError(Exception):
    """A rule config that its type's model rejects — handled as HTTP 422."""


def validate_config(rule_type: str, config: dict) -> dict:
    handler = handler_for(rule_type)
    if handler is None:
        raise RuleConfigError(f"no routing-rule type {rule_type!r} is registered")
    try:
        return handler.config_model(**(config or {})).model_dump(mode="json")
    except ValidationError as exc:
        raise RuleConfigError(str(exc)) from exc


async def get_rule(session: AsyncSession, rule_id: uuid.UUID) -> StorageRule:
    rule = await session.get(StorageRule, rule_id)
    if rule is None:
        raise NotFoundError(AttachmentEntity.RULE, rule_id)
    return rule


async def _emit(
    session: AsyncSession,
    event_type: AttachmentEvent,
    rule: StorageRule,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=AttachmentEntity.RULE,
        entity_id=rule.id,
        actor_id=actor_id,
        payload={"name": rule.name, "rule_type": rule.rule_type},
        changes=diff,
    )


async def create_rule(
    session: AsyncSession,
    *,
    name: str,
    rule_type: RuleType,
    config: dict,
    enabled: bool = True,
    actor_id: uuid.UUID | None = None,
) -> StorageRule:
    validated = validate_config(rule_type.value, config)
    tail = await session.execute(select(StorageRule.position).order_by(StorageRule.position.desc()).limit(1))
    position = (tail.scalar() or 0) + 1
    rule = StorageRule(
        name=name, rule_type=rule_type.value, config=validated, enabled=enabled, position=position
    )
    session.add(rule)
    await session.flush()
    await _emit(session, AttachmentEvent.RULE_CREATED, rule, actor_id)
    return rule


async def update_rule(
    session: AsyncSession,
    rule_id: uuid.UUID,
    *,
    name: str | None = None,
    config: dict | None = None,
    enabled: bool | None = None,
    actor_id: uuid.UUID | None = None,
) -> StorageRule:
    rule = await get_rule(session, rule_id)
    before = changes.snapshot(rule, changes.column_fields(rule))
    if name is not None:
        rule.name = name
    if config is not None:
        rule.config = validate_config(rule.rule_type, config)
    if enabled is not None:
        rule.enabled = enabled
    await session.flush()
    await _emit(
        session, AttachmentEvent.RULE_UPDATED, rule, actor_id, changes.diff_object(rule, before)
    )
    return rule


async def delete_rule(
    session: AsyncSession, rule_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> None:
    rule = await get_rule(session, rule_id)
    await _emit(session, AttachmentEvent.RULE_DELETED, rule, actor_id)
    await session.delete(rule)
    await session.flush()


async def reorder(
    session: AsyncSession, ordered_ids: list[uuid.UUID], *, actor_id: uuid.UUID | None = None
) -> list[StorageRule]:
    """Full ordered id list -> positions 1..n; unknown ids 404, omitted rules
    keep their position after the listed ones (defensive, the UI sends all).
    Every rule whose position moved gets its own `storage_rule.updated`."""
    rules = {rule.id: rule for rule in await ordered_rules(session)}
    moved: list[tuple[StorageRule, int]] = []
    for index, rule_id in enumerate(ordered_ids, start=1):
        if rule_id not in rules:
            raise NotFoundError(AttachmentEntity.RULE, rule_id)
        if rules[rule_id].position != index:
            moved.append((rules[rule_id], rules[rule_id].position))
        rules[rule_id].position = index
    await session.flush()
    for rule, previous in moved:
        await _emit(
            session,
            AttachmentEvent.RULE_UPDATED,
            rule,
            actor_id,
            [{"field": "position", "from": previous, "to": rule.position}],
        )
    return await ordered_rules(session)
