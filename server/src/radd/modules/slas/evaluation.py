"""SLA timer evaluation over items (specs 30/35/63) — shared by the engine,
the per-item endpoint, and the list/board batch endpoint.

Split out of service.py in spec 63 (policy CRUD + first-match stay there).
"""

import math
import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.automations.types import SYSTEM_ACTOR_ID
from radd.modules.comments import service as comments
from radd.modules.events import service as events
from radd.modules.items import service as items
from radd.modules.items.enums import ItemEntity
from radd.modules.reporting import timeline as reporting_timeline
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.workflow import service as workflow
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import calendar, service, timers
from .models import SlaItemState, SlaPolicy
from .schemas import BatchTimerRead
from .types import SlaEvent, SlaKind
from radd.clock import utcnow

FULL_DAY_MINUTES = 24 * 60
# Non-working days / business windows shrink the active day: the pause horizon
# covers the days a target needs at the shrunken rate, doubled, plus this slack.
HORIZON_SLACK_DAYS = 14
ALL_WEEK: frozenset[int] = frozenset(range(7))



async def evaluate_items(
    session: AsyncSession,
    policy: SlaPolicy,
    item_ids: Iterable[uuid.UUID],
    now: datetime | None = None,
) -> dict[uuid.UUID, dict[SlaKind, tuple[int, timers.TimerStatus]]]:
    """Live timer status per item for one policy: {item: {kind: (target_minutes, status)}}.

    Spec 63: callers must pass only items whose MATCHED policy is `policy`
    (first-match resolution) — this function evaluates, it does not select.
    """
    now = now or utcnow()
    id_list = list(item_ids)
    item_map = await items.items_by_ids(session, id_list)
    timelines = await reporting_timeline.build_item_timelines(session, id_list)

    state_ids = {
        segment.state_id
        for tl in timelines.values()
        for segment in tl.segments
    }
    states = await workflow.states_by_ids(session, state_ids)
    pause_names = {str(name) for name in (policy.pause_state_names or [])}

    # First qualifying response per item: a public comment by someone other than
    # the reporter or the automation system actor.
    responses: dict[uuid.UUID, datetime] = {}
    if policy.response_minutes is not None:
        for item_id, author_id, at in await comments.public_comment_times(session, id_list):
            item = item_map.get(item_id)
            if item is None or item_id in responses:
                continue
            if author_id is None or author_id == item.reporter_id or author_id == SYSTEM_ACTOR_ID:
                continue
            responses[item_id] = at

    # Work-week-only policies (spec 35): non-working days pause the clock.
    # Spec 50/67: the work week resolves per item project (project→instance→env).
    work_week_cache: dict[uuid.UUID, frozenset[int]] = {}

    async def working_days_for(project_id: uuid.UUID) -> frozenset[int]:
        if project_id not in work_week_cache:
            value = await settings_service.resolve(
                session, SettingKey.WORK_WEEK_DAYS, project_id=project_id
            )
            work_week_cache[project_id] = timers.parse_work_week(value)
        return work_week_cache[project_id]

    max_target_minutes = max(policy.response_minutes or 0, policy.resolution_minutes or 0)
    # Spec 63: an optional daily business-hours window shrinks the active day.
    windowed = (
        policy.business_start_minute is not None and policy.business_end_minute is not None
    )
    window_minutes = (
        policy.business_end_minute - policy.business_start_minute
        if windowed
        else FULL_DAY_MINUTES
    )
    # Horizon: enough calendar days to fit the target at the shrunken daily rate,
    # doubled (weekends and merged pauses), plus fixed slack.
    horizon_days = math.ceil(max_target_minutes / window_minutes) * 2 + HORIZON_SLACK_DAYS

    # Holidays (RADD-1031): dates nobody works pause the clock exactly like a
    # weekend, so they only apply to a policy that counts the WORK WEEK — a 24/7
    # policy declares that calendar time is what it measures. Resolved ONCE for
    # the whole batch's span rather than per item: the providers answer for a
    # date range, and this loop already runs over items sharing one policy.
    holidays: frozenset[date] = frozenset()
    if policy.work_week_only and item_map:
        starts = [item.created_at for item in item_map.values()]
        span_end = max(now, max(starts)) + timedelta(days=horizon_days)
        holidays = await calendar.non_working_dates(session, min(starts).date(), span_end.date())

    results: dict[uuid.UUID, dict[SlaKind, tuple[int, timers.TimerStatus]]] = {}
    for item_id, item in item_map.items():
        tl = timelines.get(item_id)
        pauses: list[tuple[datetime, datetime | None]] = []
        if tl is not None and pause_names:
            for segment in tl.segments:
                state = states.get(segment.state_id)
                if state is not None and state.name in pause_names:
                    pauses.append((segment.entered_at, segment.exited_at))
        started = item.created_at
        if policy.work_week_only or windowed:
            horizon = max(now, started) + timedelta(days=horizon_days)
            # Without work_week_only the window applies to EVERY calendar day.
            working_days = (
                await working_days_for(item.project_id) if policy.work_week_only else ALL_WEEK
            )
            if policy.work_week_only:
                pauses.extend(
                    timers.non_working_pauses(started, horizon, working_days, holidays)
                )
            if windowed:
                pauses.extend(
                    timers.business_hours_pauses(
                        started,
                        horizon,
                        policy.business_start_minute,
                        policy.business_end_minute,
                        working_days,
                    )
                )
        per_kind: dict[SlaKind, tuple[int, timers.TimerStatus]] = {}
        if policy.response_minutes is not None:
            per_kind[SlaKind.RESPONSE] = (
                policy.response_minutes,
                timers.evaluate(
                    started_at=started,
                    target_seconds=policy.response_minutes * 60,
                    pauses=pauses,
                    met_at=responses.get(item_id),
                    now=now,
                ),
            )
        if policy.resolution_minutes is not None:
            done_at = tl.done_entries[0].at if tl and tl.done_entries else None
            per_kind[SlaKind.RESOLUTION] = (
                policy.resolution_minutes,
                timers.evaluate(
                    started_at=started,
                    target_seconds=policy.resolution_minutes * 60,
                    pauses=pauses,
                    met_at=done_at,
                    now=now,
                ),
            )
        results[item_id] = per_kind
    return results


# --- batch endpoint compute (spec 63: list/board chips) ---


async def batch_sla(
    session: AsyncSession, actor: User, item_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[BatchTimerRead]]:
    """Live timers for the items the actor can read, via each item's matched
    policy — grouped per policy so evaluate_items runs once per group."""
    item_map = await items.items_by_ids(session, item_ids)
    projects: dict[uuid.UUID, Project] = {}
    for item in item_map.values():
        if item.project_id not in projects:
            projects[item.project_id] = await projects_service.get_project(
                session, item.project_id
            )
    permissions = await authz.permissions_for_projects(session, actor, list(projects.values()))
    readable = [
        item
        for item in item_map.values()
        if authz.holds_base(permissions.get(item.project_id, frozenset()), Permission.ITEM_READ)
    ]
    matched = await service.matched_policies(session, readable)
    grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
    policy_by_id: dict[uuid.UUID, SlaPolicy] = {}
    for item_id, policy in matched.items():
        grouped.setdefault(policy.id, []).append(item_id)
        policy_by_id[policy.id] = policy
    result: dict[uuid.UUID, list[BatchTimerRead]] = {}
    for policy_id, group in grouped.items():
        policy = policy_by_id[policy_id]
        for item_id, per_kind in (await evaluate_items(session, policy, group)).items():
            result[item_id] = [
                BatchTimerRead(
                    policy_name=policy.name,
                    kind=kind,
                    due_at=status.due_at,
                    met_at=status.met_at,
                    breached=status.breached,
                    paused=status.paused,
                    remaining_seconds=status.remaining_seconds,
                )
                for kind, (_target, status) in per_kind.items()
            ]
    return result


# --- engine bookkeeping (breach events fire exactly once) ---


def _sla_payload(
    policy: SlaPolicy,
    item_id: uuid.UUID,
    kind: SlaKind,
    status: timers.TimerStatus,
    item_refs: dict[uuid.UUID, dict],
) -> dict:
    """`item_key` became `item` (RADD-922). It was the only place in the codebase
    that spelled the issue key that way, which is why `googlechat/formatter.py`
    had two branches for one concept and `notify/consumer.py` had four."""
    return {
        "item": item_refs.get(item_id),
        "policy_id": str(policy.id),
        "policy_name": policy.name,
        "kind": kind.value,
        "due_at": status.due_at.isoformat() if status.due_at else None,
    }


def due_soon(policy: SlaPolicy, status: timers.TimerStatus) -> bool:
    """Spec 69: the timer is live (not met/breached/paused) and its remaining
    active time has dropped to the policy's warning window. Pure."""
    return (
        policy.warning_minutes is not None
        and status.met_at is None
        and not status.breached
        and status.remaining_seconds is not None
        and status.remaining_seconds <= policy.warning_minutes * 60
    )


async def sync_states(
    session: AsyncSession,
    policy: SlaPolicy,
    evaluated: dict[uuid.UUID, dict[SlaKind, tuple[int, timers.TimerStatus]]],
    item_refs: dict[uuid.UUID, dict],
) -> int:
    """Upsert bookkeeping rows; emit sla.breached for NEW breaches and (spec 69)
    sla.due_soon ONCE per item/policy/kind when the warning window opens.
    Returns count emitted (breaches + warnings)."""
    if not evaluated:
        return 0
    result = await session.execute(
        select(SlaItemState).where(
            SlaItemState.policy_id == policy.id,
            SlaItemState.item_id.in_(list(evaluated)),
        )
    )
    rows = {row.item_id: row for row in result.scalars()}
    now = utcnow()
    emitted = 0
    for item_id, per_kind in evaluated.items():
        row = rows.get(item_id)
        if row is None:
            row = SlaItemState(item_id=item_id, policy_id=policy.id)
            session.add(row)
        for kind, (_target, status) in per_kind.items():
            prefix = "response" if kind is SlaKind.RESPONSE else "resolution"
            setattr(row, f"{prefix}_due_at", status.due_at)
            setattr(row, f"{prefix}_met_at", status.met_at)
            already = getattr(row, f"{prefix}_breached_at")
            if status.breached and already is None:
                setattr(row, f"{prefix}_breached_at", now)
                await events.emit(
                    session,
                    event_type=SlaEvent.BREACHED,
                    entity_type=ItemEntity.ITEM,
                    entity_id=item_id,
                    actor_id=None,
                    payload=_sla_payload(policy, item_id, kind, status, item_refs),
                )
                emitted += 1
            warned = getattr(row, f"warned_{prefix}_at")
            if warned is None and already is None and due_soon(policy, status):
                setattr(row, f"warned_{prefix}_at", now)
                await events.emit(
                    session,
                    event_type=SlaEvent.DUE_SOON,
                    entity_type=ItemEntity.ITEM,
                    entity_id=item_id,
                    actor_id=None,
                    payload={
                        **_sla_payload(policy, item_id, kind, status, item_refs),
                        "remaining_seconds": status.remaining_seconds,
                    },
                )
                emitted += 1
    await session.flush()
    return emitted


async def terminal_item_ids(
    session: AsyncSession, policy: SlaPolicy, item_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Items whose every targeted timer is already met or breached — skippable."""
    if not item_ids:
        return set()
    result = await session.execute(
        select(SlaItemState).where(
            SlaItemState.policy_id == policy.id,
            SlaItemState.item_id.in_(item_ids),
        )
    )
    terminal: set[uuid.UUID] = set()
    for row in result.scalars():
        done = True
        if policy.response_minutes is not None:
            done = row.response_met_at is not None or row.response_breached_at is not None
        if done and policy.resolution_minutes is not None:
            done = row.resolution_met_at is not None or row.resolution_breached_at is not None
        if done:
            terminal.add(row.item_id)
    return terminal
