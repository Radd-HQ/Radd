"""Rule-chain evaluation (spec 102): enabled rules by position, first non-None
answer wins, everything else lands on the default host. A rule that cannot run
falls through — a type with no live provider (its plugin disabled or
uninstalled: `ai`'s `llm` with `ai` off), a stale config, a host that vanished —
so routing degrades toward the default, never toward an error."""

import logging
import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import sockets

from .. import hosts
from ..models import StorageHost, StorageRule
from ..types import RuleType
from .context import RoutingContext

logger = logging.getLogger(__name__)


async def ordered_rules(session: AsyncSession) -> list[StorageRule]:
    result = await session.execute(select(StorageRule).order_by(StorageRule.position))
    return list(result.scalars())


def handler_for(rule_type: str):
    return sockets.provider(sockets.Socket.STORAGE_ROUTING_RULE, rule_type)


async def choice_reachable(
    session: AsyncSession, *, source_ip: str | None, content_types: list[str]
) -> tuple[bool, str | None]:
    """Would an upload with these content types actually REACH an enabled
    user-choice rule — or is it captured first (spec 102 "ask only when the
    answer matters")? Returns (reachable, name of the pre-empting rule).

    Prediction mirrors `decide`, and each rule TYPE answers for itself through
    the socket's optional `captured_types` (RADD-1387): a CIDR rule matching the
    caller's IP captures everything; the `ai` plugin's llm rule captures the
    types its prefixes cover while its feature is live. A type without the
    method — or with no provider at all, its plugin disabled — is treated as
    non-capturing: over-asking beats silently discarding an answer.
    """
    remaining = set(content_types) or {""}
    for rule in await ordered_rules(session):
        if not rule.enabled:
            continue
        if rule.rule_type == RuleType.USER_CHOICE.value:
            return True, None
        handler = handler_for(rule.rule_type)
        captured_types = getattr(handler, "captured_types", None)
        if captured_types is None:
            continue
        try:
            config = handler.config_model(**(rule.config or {}))
        except ValidationError:
            continue
        remaining -= await captured_types(
            session, config, source_ip=source_ip, content_types=frozenset(remaining)
        )
        if not remaining:
            return False, rule.name  # decided before the ask; nothing reaches it
    return False, None  # no enabled user-choice rule in the chain at all


def rule_types() -> list[str]:
    """Every rule type a new rule may use — the LIVE providers on the socket,
    so a type whose plugin is disabled is not offered (RADD-1387)."""
    return sorted(sockets.providers(sockets.Socket.STORAGE_ROUTING_RULE))


async def decide(session: AsyncSession, ctx: RoutingContext) -> StorageHost:
    for rule in await ordered_rules(session):
        if not rule.enabled:
            continue
        handler = handler_for(rule.rule_type)
        if handler is None:
            logger.warning("storage rule %r: no handler for type %r", rule.name, rule.rule_type)
            continue
        try:
            config = handler.config_model(**(rule.config or {}))
        except ValidationError:
            logger.warning("storage rule %r: stored config no longer validates", rule.name)
            continue
        host_id: uuid.UUID | None = await handler.evaluate(session, ctx, config)
        if host_id is None:
            continue
        host = await session.get(StorageHost, host_id)
        if host is None:
            logger.warning("storage rule %r: names a vanished host — skipped", rule.name)
            continue
        return host
    return await hosts.require_default(session)
