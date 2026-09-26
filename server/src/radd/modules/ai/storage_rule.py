"""The `llm` storage routing rule, this plugin's provider on STORAGE_ROUTING_RULE
(spec 102). An admin prompt plus ENUMERATED answers mapped to hosts: the model
cannot invent an unmapped answer, and any failure falls through to the next rule.
Duck-typed on the routing context (`content_type`, `content`)."""

import asyncio
import logging
import uuid
from collections.abc import Collection
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import client, features
from .types import AiDisabledError, AiFeature, AiRole, AiUpstreamError

logger = logging.getLogger(__name__)


class LlmAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=100)
    host_id: uuid.UUID


class LlmConfig(BaseModel):
    prompt: str = Field(min_length=1)
    answers: list[LlmAnswer] = Field(min_length=2)  # one answer = no decision to make
    content_type_prefixes: list[str] = ["image/"]
    timeout_seconds: float = Field(default=10.0, ge=1, le=120)


def _covers(config: LlmConfig, content_type: str) -> bool:
    return any(content_type.startswith(prefix) for prefix in config.content_type_prefixes)


class LlmRule:
    """`RoutingRule` over the vision role (Settings → AI → LLM storage routing)."""

    config_model = LlmConfig

    async def evaluate(self, session: AsyncSession, ctx: Any, config: LlmConfig) -> uuid.UUID | None:
        if not _covers(config, ctx.content_type) or ctx.content is None:
            return None
        if not await features.feature_enabled(session, AiFeature.STORAGE_ROUTING):
            return None
        mapping = {entry.answer: entry.host_id for entry in config.answers}
        try:
            choice = await asyncio.wait_for(
                client.complete_choice(
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

    async def captured_types(
        self,
        session: AsyncSession,
        config: LlmConfig,
        *,
        source_ip: str | None,
        content_types: Collection[str],
    ) -> set[str]:
        """The content types this rule decides ahead of an "ask the uploader"
        rule: those its prefixes cover — while the feature is live. Dormant, it
        decides nothing, so the uploader is asked."""
        if not await features.feature_enabled(session, AiFeature.STORAGE_ROUTING):
            return set()
        return {content_type for content_type in content_types if _covers(config, content_type)}
