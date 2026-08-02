"""The schedule clock (spec 69): every RADD_AUTOMATION_SCHEDULER_INTERVAL, due
automation_schedule_state rows (next_run_at <= now, rule enabled) each emit one
synthetic `automation.scheduled` outbox event and advance next_run_at IN THE
SAME TRANSACTION — at-most-once per occurrence; a window missed while the server
was down fires once on the next tick, never a replayed backlog. The engine's
consumer path does the actual rule execution (engine.apply_scheduled)."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.events import service as events
from radd.worker import PeriodicLoop

from radd import schedule as schedule_math
from .models import AutomationRule, AutomationScheduleState
from .types import SYSTEM_ACTOR_ID, AutomationEntity, AutomationEvent

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def run_once(session_factory=SessionLocal) -> int:
    """Fire every due scheduled rule once. Returns the number of events emitted."""
    now = _utcnow()
    fired = 0
    async with session_factory() as session:
        result = await session.execute(
            select(AutomationScheduleState, AutomationRule)
            .join(AutomationRule, AutomationRule.id == AutomationScheduleState.rule_id)
            .where(
                AutomationScheduleState.next_run_at <= now,
                AutomationRule.enabled.is_(True),
            )
        )
        for state, rule in result.all():
            if rule.schedule is None:  # defensive: state row without a config
                logger.warning("automations: rule %s has schedule state but no schedule", rule.id)
                await session.delete(state)
                continue
            await events.emit(
                session,
                event_type=AutomationEvent.SCHEDULED,
                entity_type=AutomationEntity.AUTOMATION,
                entity_id=rule.id,
                actor_id=SYSTEM_ACTOR_ID,  # system-emitted by design (spec 69)
                payload={
                    "rule_id": str(rule.id),
                    "scheduled_for": state.next_run_at.isoformat(),
                },
            )
            state.last_run_at = now
            state.next_run_at = schedule_math.next_run(rule.schedule, now, settings.scheduler_tz)
            fired += 1
        await session.commit()
    return fired


_loop = PeriodicLoop(
    run_once,
    interval=lambda: settings.automation_scheduler_interval,
    name="automations.scheduler",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
)

start = _loop.start
stop = _loop.stop
