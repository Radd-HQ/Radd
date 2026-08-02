"""The Google Chat outbox consumer: selected events → incoming-webhook posts.

Formatting is pure (formatter.py); the cursor/commit shape is the shared
head-seeded scaffold (`events.runner.run_head_seeded`): first start seeds the
cursor AT THE STREAM HEAD — a chat channel must not be spammed with the full
event backlog (spec 47) — and messages are delivered post-commit (at-most-once;
the 2026-07-22 consolidation moved delivery after the cursor commit, trading
the old crash-window duplicate for a dropped ping). Delivery failures log +
advance: an incoming webhook ping is not worth a retry queue — the webhooks
module is the guaranteed delivery path.
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.events import runner
from radd.modules.events.models import Event

from . import formatter
from .types import BATCH_SIZE, CONSUMER_NAME, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


def selected_event_types() -> frozenset[str]:
    """The csv RADD_GOOGLECHAT_EVENT_TYPES setting as a set of wire strings."""
    return frozenset(
        part.strip() for part in settings.googlechat_event_types.split(",") if part.strip()
    )


async def run_once() -> int:
    selected = selected_event_types()  # once per batch, closed over by the planner

    async def plan(session: AsyncSession, event: Event) -> str | None:
        return formatter.format_message(event, selected=selected, base_url=settings.app_base_url)

    return await runner.run_head_seeded(
        CONSUMER_NAME, batch_size=BATCH_SIZE, plan=plan, deliver=_deliver_all
    )


async def _deliver_all(texts: list[str]) -> None:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for text in texts:
            try:
                response = await client.post(settings.googlechat_webhook_url, json={"text": text})
                response.raise_for_status()
            except Exception:
                # Log + advance — fire-and-forget by design (spec 47).
                logger.exception("googlechat: delivery failed (message dropped)")
