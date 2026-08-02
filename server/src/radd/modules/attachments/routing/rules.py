"""The three builtin routing-rule types (spec 102).

Every handler answers a host id or None (fall through) — a rule can only
NARROW where an upload goes, never error an upload out. The LLM rule is the
spec-102/101 seam: an admin-authored filtering prompt plus ENUMERATED answers,
each mapped to a host; structured output means the model cannot invent an
unmapped answer, and any failure (timeout, refusal, feature off, module gone)
falls through to the next rule.
"""

import asyncio
import ipaddress
import logging
import uuid

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .context import RoutingContext

logger = logging.getLogger(__name__)


# --- user choice ---------------------------------------------------------------


class UserChoiceConfig(BaseModel):
    """No knobs: the offered set is every host flagged user_selectable."""


class UserChoiceRule:
    config_model = UserChoiceConfig

    async def evaluate(
        self, session: AsyncSession, ctx: RoutingContext, config: UserChoiceConfig
    ) -> uuid.UUID | None:
        """The user's pick, honored only if it names a selectable host — so
        API/SDK/importer uploads (which never prompt) sail through, and a stale
        or forged choice cannot reach a non-selectable host."""
        if ctx.chosen_host_id is None:
            return None
        from ..models import StorageHost

        host = await session.get(StorageHost, ctx.chosen_host_id)
        if host is None or not host.user_selectable:
            return None
        return host.id


# --- CIDR ----------------------------------------------------------------------


class CidrRange(BaseModel):
    cidr: str
    host_id: uuid.UUID


class CidrConfig(BaseModel):
    ranges: list[CidrRange] = Field(min_length=1)


def match_cidr(source_ip: str | None, ranges: list[CidrRange]) -> uuid.UUID | None:
    """First range containing the address (pure). Unparseable input -> None."""
    if not source_ip:
        return None
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return None
    for entry in ranges:
        try:
            if address in ipaddress.ip_network(entry.cidr, strict=False):
                return entry.host_id
        except ValueError:
            logger.warning("storage cidr rule: invalid range %r skipped", entry.cidr)
    return None


class CidrRule:
    config_model = CidrConfig

    async def evaluate(
        self, session: AsyncSession, ctx: RoutingContext, config: CidrConfig
    ) -> uuid.UUID | None:
        return match_cidr(ctx.source_ip, config.ranges)


# --- LLM (vision) --------------------------------------------------------------


class LlmAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=100)
    host_id: uuid.UUID


class LlmConfig(BaseModel):
    prompt: str = Field(min_length=1)
    answers: list[LlmAnswer] = Field(min_length=2)  # one answer = no decision to make
    content_type_prefixes: list[str] = ["image/"]
    timeout_seconds: float = Field(default=10.0, ge=1, le=120)


class LlmRule:
    config_model = LlmConfig

    async def evaluate(
        self, session: AsyncSession, ctx: RoutingContext, config: LlmConfig
    ) -> uuid.UUID | None:
        if not any(ctx.content_type.startswith(p) for p in config.content_type_prefixes):
            return None
        if ctx.content is None:
            return None
        try:  # the ai module is optional — absent/disabled means fall through
            from radd.modules.ai import client as ai_client
            from radd.modules.ai import features as ai_features
            from radd.modules.ai.types import (
                AiDisabledError,
                AiFeature,
                AiRole,
                AiUpstreamError,
            )
        except ImportError:
            return None
        if not await ai_features.feature_enabled(session, AiFeature.STORAGE_ROUTING):
            return None
        mapping = {entry.answer: entry.host_id for entry in config.answers}
        try:
            choice = await asyncio.wait_for(
                ai_client.complete_choice(
                    session,
                    AiRole.VISION,
                    prompt=config.prompt,
                    choices=list(mapping),
                    image_bytes=ctx.content(),
                    image_media_type=ctx.content_type,
                ),
                timeout=config.timeout_seconds,
            )
        except (TimeoutError, AiUpstreamError, AiDisabledError) as exc:
            logger.warning("storage llm rule: fell through (%s)", exc.__class__.__name__)
            return None
        return mapping.get(choice)
