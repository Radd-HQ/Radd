"""The schedule clock (spec 69): every RADD_AUTOMATION_SCHEDULER_INTERVAL, due
automation_schedule_state rows (next_run_at <= now, rule enabled) each emit one
synthetic `automation.scheduled` outbox event and advance next_run_at IN THE
SAME TRANSACTION — at-most-once per occurrence; a window missed while the server
was down fires once on the next tick, never a replayed backlog. The engine's
consumer path does the actual rule execution (engine.apply_scheduled)."""

import logging

from sqlalchemy import select

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.events import service as events
from radd.worker import PeriodicLoop

from radd import schedule as schedule_math
from . import runs
from .models import Automation, AutomationScheduleState, TriggerBinding
from .types import SYSTEM_ACTOR_ID, AutomationEntity, AutomationEvent
from radd.clock import utcnow

logger = logging.getLogger(__name__)



async def run_once(session_factory=SessionLocal) -> int:
    """Fire every due scheduled rule once. Returns the number of events emitted."""
    now = utcnow()
    fired = 0
    async with session_factory() as session:
        # Joined through the trigger BINDING, not the automation: since spec 116
        # a graph may hold several schedule triggers, each with its own clock,
        # and the schedule to advance belongs to the node that came due.
        result = await session.execute(
            select(AutomationScheduleState, Automation, TriggerBinding)
            .join(Automation, Automation.id == AutomationScheduleState.automation_id)
            .join(
                TriggerBinding,
                (TriggerBinding.automation_id == AutomationScheduleState.automation_id)
                & (TriggerBinding.node_id == AutomationScheduleState.node_id),
            )
            .where(
                AutomationScheduleState.next_run_at <= now,
                Automation.enabled.is_(True),
            )
        )
        for state, rule, binding in result.all():
            if binding.schedule is None:  # defensive: state row without a config
                logger.warning(
                    "automations: %s trigger %s has schedule state but no schedule",
                    rule.id, state.node_id,
                )
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
                    # WHICH trigger came due — the engine starts the run there,
                    # so a graph with two schedules runs the right branch.
                    "node_id": state.node_id,
                    "scheduled_for": state.next_run_at.isoformat(),
                },
            )
            state.last_run_at = now
            state.next_run_at = schedule_math.next_run(
                binding.schedule, now, settings.scheduler_tz
            )
            fired += 1
        # The run-history sweep rides the same clock (RADD-1266): a tick a
        # minute over an indexed column is nothing, and a second loop for it
        # would be a second thing to start, stop and monitor.
        await runs.sweep(session, now=now)
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
